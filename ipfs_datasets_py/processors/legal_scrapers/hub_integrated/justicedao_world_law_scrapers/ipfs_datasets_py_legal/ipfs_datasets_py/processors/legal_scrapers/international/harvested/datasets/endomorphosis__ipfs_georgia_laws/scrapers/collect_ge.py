#!/usr/bin/env python3
"""Georgia: matsne.gov.ge (Wayback PDFs) + parliament.ge/_special/kan/files (CDX PDF snapshots).

Live matsne.gov.ge is WAF/Access Denied — no bypass.
Live parliament.ge kan paths now return SPA HTML; use Wayback of CDX
application/pdf snapshots with their timestamps.
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, pdf_to_text, save_instrument, setup_log, slug_id
import archive_fallbacks as af

CC, COUNTRY, LANG = "ge", "Georgia", "ka"
SOURCE_TYPE = "georgia_official_pdf"
LICENSE = (
    "Official texts of the Legislative Herald of Georgia (matsne.gov.ge) and "
    "Parliament of Georgia (_special/kan archive). Authentic publication prevails. "
    "Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://matsne.gov.ge/)"
ART = re.compile(r"(?m)^\s*((?:მუხლი|Article)\s+[0-9]+[A-Za-zა-ჰ]?)\b")
log = logging.getLogger("ge")

SEED_PDF = [
    "https://matsne.gov.ge/ka/document/download/31702/0/ge/pdf",
    "https://matsne.gov.ge/ka/document/download/11598/0/ge/pdf",
    "https://matsne.gov.ge/ka/document/download/19300/0/ge/pdf",
    "https://matsne.gov.ge/ka/document/download/30346/0/ge/pdf",
    "https://matsne.gov.ge/ka/document/download/5827307/0/ge/pdf",
    "https://matsne.gov.ge/document/download/31702/75/en/pdf",
]

SPA_MARK = re.compile(r"(პლენარული სხდომა|მოძებნე კანონმდებლობა|just a moment|cf-browser)", re.I)


def _is_garbage(text: str) -> bool:
    if not text or len(text) < 200:
        return True
    if SPA_MARK.search(text[:2000]):
        return True
    if text.lstrip().startswith("%PDF"):
        return True
    return False


def _fetch_wayback_pdf(url: str, timestamp: str | None = None) -> dict:
    out = {"status": "error", "text": "", "content": b"", "source_url": url, "method": "", "error": ""}
    try:
        w = af.get_wayback_content(url, timestamp=timestamp)
    except Exception as exc:
        out["error"] = f"wayback:{exc}"
        return out
    if w.get("status") != "success":
        out["error"] = f"wayback:{w.get('error')}"
        return out
    raw = w.get("content") or b""
    if isinstance(raw, str):
        raw = raw.encode("latin-1", "replace")
    if raw[:4] != b"%PDF":
        idx = raw.find(b"%PDF", 0, 8192)
        if idx >= 0:
            raw = raw[idx:]
        else:
            out["error"] = "not_pdf"
            return out
    text = pdf_to_text(raw)
    if _is_garbage(text):
        out["error"] = "pdf_garbage_or_short"
        return out
    out.update(status="success", text=text, content=raw, method="wayback_pdf",
               source_url=w.get("wayback_url") or url)
    return out


def discover():
    items, seen = [], set()

    def add_parl(orig, ts):
        url = (orig or "").split("#")[0].replace("http://", "https://").replace(":80/", "/")
        low = url.lower()
        if "parliament.ge" not in low:
            return
        if "/_special/kan/files/" not in low and "/kan/files/" not in low:
            return
        if ".pdf" not in low:
            return
        name = Path(unquote(urlparse(url).path)).name
        ident = f"parl-{name.replace('.pdf', '')}"
        if ident in seen:
            return
        seen.add(ident)
        items.append((ident, url, ts, "parl"))

    def add_matsne(orig, ts=None):
        url = (orig or "").split("#")[0].replace("http://", "https://").replace(":80/", "/")
        low = url.lower()
        if "matsne.gov.ge" not in low or "/document/download" not in low:
            return
        if "/pdf" not in low:
            return
        m = re.search(r"/document/download/?-?/?(\d+)", url)
        ident = m.group(1) if m else Path(url.rstrip("/")).name
        key = f"matsne-{ident}"
        if key in seen:
            return
        seen.add(key)
        items.append((ident, url, ts, "matsne"))

    limit = env_int("CDX_LIMIT", 400)
    for prefix in (
        "www.parliament.ge/_special/kan/files/",
        "parliament.ge/_special/kan/files/",
    ):
        for h in cdx_urls(prefix, limit=limit, match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            add_parl(h.get("original"), h.get("timestamp"))

    for u in SEED_PDF:
        add_matsne(u)
    for prefix in (
        "matsne.gov.ge/ka/document/download/",
        "www.matsne.gov.ge/ka/document/download/",
        "matsne.gov.ge/document/download/",
    ):
        for h in cdx_urls(prefix, limit=min(250, limit), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            add_matsne(h.get("original"), h.get("timestamp"))
        for h in cdx_urls(prefix, limit=min(200, limit), match_type="prefix"):
            orig = h.get("original") or ""
            if "/pdf" in orig.lower():
                add_matsne(orig, h.get("timestamp"))

    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url, ts, kind in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = _fetch_wayback_pdf(url, ts)
        if got.get("status") != "success" and kind == "matsne":
            got = fetch_official(url, ua=UA, verify=False, min_text=200)
        text = got.get("text") or ""
        if got.get("status") != "success" or _is_garbage(text):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url,
                             "reason": got.get("error") or "garbage"})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 12 and not SPA_MARK.search(line):
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or f"Georgia {ident}", text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_ge.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method"), "kind": kind},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s kind=%s method=%s chars=%s", ident[:60], kind, got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY,
        source="matsne.gov.ge Legislative Herald + parliament.ge kan CDX PDFs",
        source_urls=["https://matsne.gov.ge/", "https://www.parliament.ge/"],
        license_text=LICENSE,
        discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage=(
            "catalog-backed incomplete; live matsne WAF skipped; "
            "parliament.ge live SPA skipped — Wayback of CDX application/pdf snapshots only"
        ),
        notes="No WAF bypass. Official Matsne + Parliament kan PDF URLs only. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
