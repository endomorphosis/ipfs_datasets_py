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
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False,
                capture_output=True,
                timeout=180,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext: %s", exc)
    return ""


def split_custom(text: str, law_id: str, source_url: str, date: Optional[str], pattern: Optional[re.Pattern]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if not pattern:
        return docs
    matches = list(pattern.finditer(text or ""))
    if len(matches) < 2:
        return docs if len(docs) >= 2 else []
    out = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 20:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-zA-Z0-9\u0400-\u04FF\u0530-\u058F-]+", "-", num.lower()).strip("-")[:80]
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


def live_get(url: str, *, ua: str = DEFAULT_UA, timeout: tuple = (20, 90), verify: bool = True, retries: int = 3):
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
    try:
        r = live_get(url, ua=ua, verify=verify)
        body = r.content or b""
        ctype = r.headers.get("content-type") or ""
        if r.status_code == 200 and body:
            if body[:4] == b"%PDF" or "pdf" in ctype.lower():
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
            elif body[:4] == b"%PDF":
                out["error"] = "pdf_extract_failed"
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
                if (isinstance(raw_b, bytes) and raw_b[:4] == b"%PDF") or (raw_t[:4] == "%PDF"):
                    pdf_bytes = raw_b if isinstance(raw_b, bytes) and raw_b[:4] == b"%PDF" else raw_t.encode("latin-1", "replace")
                    text = pdf_to_text(pdf_bytes)
                    if len(text) >= min_text and not text.lstrip().startswith("%PDF"):
                        out.update(
                            status="success",
                            text=text,
                            content=pdf_bytes,
                            method="wayback_pdf",
                            source_url=w.get("url") or url,
                            content_type="application/pdf",
                        )
                        return out
                    out["error"] = (out.get("error") or "") + ";pdf_extract_failed"
                    return out
                if not raw_t and isinstance(raw_b, bytes):
                    raw_t = raw_b.decode("utf-8", "replace")
                if raw_t.lstrip().startswith("%PDF") or "endobj" in raw_t[:200]:
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
