#!/usr/bin/env python3
"""Andorra: Butlletí Oficial del Principat d'Andorra (BOPA) via official public API + documents.bopa.ad.

Official sources only:
  - https://www.bopa.ad/ (SPA; discovery via published Azure Functions used by the site)
  - https://bopaazurefunctions.azurewebsites.net/api/* (optional configured public API access)
  - https://documents.bopa.ad/bopa-documents/{folder}/html|pdf/...

No F5/Cloudflare WAF bypass. Prefer live HTML; PDF fallback; Wayback of official URLs only if live blocked.
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    DEFAULT_UA,
    ROOT,
    append_catalog,
    existing_ids,
    html_to_text,
    http_get,
    iso_date,
    log_failure,
    slug_id,
    utcnow,
    write_summary,
)
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log

CC, COUNTRY, LANG = "ad", "Andorra", "ca"
SOURCE_TYPE = "bopa"
LICENSE = (
    "Butlletí Oficial del Principat d'Andorra (BOPA) — official gazette texts at "
    "https://www.bopa.ad/ and https://documents.bopa.ad/. Authentic official text prevails. "
    "Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.bopa.ad/"
API = "https://bopaazurefunctions.azurewebsites.net"
# Configure public BOPA function keys separately; never embed credentials in source.
CODE_MONTH = os.environ.get("BOPA_MONTH_API_CODE", "")
CODE_DOCS = os.environ.get("BOPA_DOCUMENTS_API_CODE", "")
BLOB = "https://documents.bopa.ad/bopa-documents"
ART = re.compile(
    r"(?im)^\s*((?:Article|Artícle|Art\.?|ARTICLE)\s+(?:únic|unic|[\d]+[ºªa.]?)|"
    r"(?:Disposici[oó]\s+(?:addicional|transit[oò]ria|final)|Capítol|Títol)\b)"
)
log = logging.getLogger("ad")



def bulletin_num_key(num: int | str) -> tuple:
    """Sort key for BOPA issue nums (numeric + extras like E1/F0)."""
    s = str(num).strip()
    if re.fullmatch(r"\d+", s):
        return (0, int(s.lstrip("0") or "0"), "")
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", s)
    if m:
        return (1, int(m.group(2)), m.group(1).upper())
    return (2, 0, s)


def safe_bulletin_slug(num: int | str) -> str:
    s = str(num).strip()
    if re.fullmatch(r"\d+", s):
        return f"{int(s.lstrip('0') or '0'):03d}"
    return re.sub(r"[^A-Za-z0-9]+", "", s) or "x"

def folder_for(year: int, num: int | str) -> str:
    """BOPA blob folder: (year-1988) zero-padded 3 + issue num zero-padded 3.

    Extra issues (E1, F0, …) are non-numeric; doc_urls prefers metadata_storage_path.
    """
    y = int(year) - 1988
    s = str(num).strip()
    if re.fullmatch(r"\d+", s):
        n = int(s.lstrip("0") or "0")
        return f"{y:03d}{n:03d}"
    return f"{y:03d}{safe_bulletin_slug(s)}"


def decode_sumari(s: str | None) -> str:
    if not s:
        return ""
    try:
        return unquote(s.replace("+", " ")).strip()
    except Exception:
        return str(s).strip()


def api_get_q(path: str, params: dict, *, timeout: int = 90):
    """Query the public API through the shared robots-gated HTTP session."""
    from urllib.parse import urlencode
    if not params.get("code"):
        log.info("BOPA API key not configured for %s; retaining PDF discovery", path)
        return None
    try:
        response = http_get(f"{API}{path}?{urlencode(params)}", ua=UA, sleep=0.35,
                            retries=3, timeout=(20, min(120, max(1, timeout))),
                            headers={"Accept": "application/json"})
        if response.status_code == 200 and response.content:
            return response.json()
    except Exception:
        # Do not log query strings: configured API codes belong only in the request.
        log.warning("BOPA API request failed for %s", path)
    return None


def discover_bulletins(year_start: int, year_end: int) -> list[dict]:
    catp = ROOT / CC / "raw" / "catalog_bulletins.jsonl"
    catp.parent.mkdir(parents=True, exist_ok=True)
    items, seen = [], set()
    if catp.exists() and catp.stat().st_size > 200:
        for line in catp.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            key = (str(row.get("year")), str(row.get("num")))
            if key in seen:
                continue
            seen.add(key)
            items.append(row)
        if items:
            items.sort(key=lambda r: (int(r["year"]),) + bulletin_num_key(r.get("num") or ""))
            log.info("resume bulletin catalog %s", len(items))
            return items

    if not CODE_MONTH:
        return items
    now = datetime.now(timezone.utc)
    for year in range(year_start, year_end + 1):
        for month in range(1, 13):
            if year == now.year and month > now.month:
                break
            date = f"{year:04d}-{month:02d}-15"
            data = api_get_q(
                "/api/GetMonthButlletins",
                {"code": CODE_MONTH, "date": date},
            )
            if not isinstance(data, list):
                continue
            for row in data:
                num = str(row.get("num") or "").strip()
                if not num:
                    continue
                # year from dataPublicacio when available
                dp = row.get("dataPublicacio") or ""
                y = int(dp[:4]) if re.match(r"^\d{4}", dp) else year
                key = (str(y), num)
                if key in seen:
                    continue
                seen.add(key)
                rec = {
                    "year": y,
                    "num": num,
                    "numBOPA": row.get("numBOPA"),
                    "dataPublicacio": dp,
                    "isExtra": bool(row.get("isExtra")),
                }
                items.append(rec)
                with catp.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log.info("bulletins through %s-%02d catalog=%s", year, month, len(items))
    items.sort(key=lambda r: (int(r["year"]),) + bulletin_num_key(r.get("num") or ""))
    return items


def docs_for_bulletin(year: int, num: str) -> list[dict]:
    data = api_get_q(
        "/api/GetDocumentsByBOPA",
        {"code": CODE_DOCS, "numBOPA": num, "year": year},
        timeout=120,
    )
    if not isinstance(data, dict):
        return []
    out = []
    for row in data.get("paginatedDocuments") or []:
        doc = row.get("document") if isinstance(row, dict) else None
        if isinstance(doc, dict):
            out.append(doc)
    return out


def doc_urls(doc: dict, year: int, num: str) -> tuple[str, str, str]:
    name = (doc.get("nomDocument") or doc.get("metadata_storage_name") or "").strip()
    stem = re.sub(r"\.(html|pdf|aspx)$", "", name, flags=re.I)
    folder = folder_for(year, num)
    # Prefer path year/num from storage path when present
    mpath = doc.get("metadata_storage_path") or ""
    m = re.search(r"/bopa-documents/(\d{6})/(?:html|pdf)/([^/]+)\.(?:html|pdf)", mpath)
    if m:
        folder, stem = m.group(1), re.sub(r"\.(html|pdf)$", "", m.group(2), flags=re.I)
    html_u = f"{BLOB}/{folder}/html/{stem}.html"
    pdf_u = f"{BLOB}/{folder}/pdf/{stem}.pdf"
    return stem, html_u, pdf_u


def fetch_doc_text(html_u: str, pdf_u: str) -> tuple[str, str, str]:
    """Return (text, source_url, method). Prefer HTML; PDF fallback; Wayback via fetch_official."""
    got = fetch_official(html_u, ua=UA, verify=True, wayback=True, min_text=80)
    if got.get("status") == "success" and (got.get("text") or "").strip():
        return got["text"], html_u, got.get("method") or "http_html"
    got2 = fetch_official(pdf_u, ua=UA, verify=True, wayback=True, min_text=80)
    if got2.get("status") == "success" and (got2.get("text") or "").strip():
        return got2["text"], pdf_u, got2.get("method") or "http_pdf"
    return "", html_u, got.get("error") or got2.get("error") or "empty"


def _document_key(url: str) -> str:
    """Treat the HTML and PDF representations of one BOPA document as one source."""
    from urllib.parse import urlsplit
    parts = urlsplit(unquote(url or ""))
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/(html|pdf)/", "/document/", parts.path)
    path = re.sub(r"\.(html|pdf)$", "", path, flags=re.I)
    return host + path.rstrip("/")


def _content_fingerprint(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()


def discover_pdf_issues() -> list[tuple[str, str]]:
    """Retain upstream CDX discovery of official PDF issues when the API is thin/unavailable."""
    from urllib.parse import urlsplit
    items, seen = [], set()
    for prefix in ("www.bopa.ad/", "bopa.ad/", "documents.bopa.ad/bopa-documents/"):
        for hit in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 800), match_type="prefix",
                            extra_filters=["mimetype:application/pdf"]):
            url = (hit.get("original") or "").split("#")[0]
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            if not (host == "bopa.ad" or host.endswith(".bopa.ad")):
                continue
            if not (parts.path.lower().endswith(".pdf") or "/pdf/" in parts.path.lower()):
                continue
            key = _document_key(url)
            if key in seen:
                continue
            seen.add(key)
            ident = re.sub(r"[^a-z0-9]+", "-", Path(unquote(parts.path)).stem.lower()).strip("-")[:120]
            items.append(("ad-" + (ident or "doc"), url))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    t_start = time.time()
    max_new = env_int("MAX_NEW", 40)  # 0 explicitly removes the cap
    max_seconds = env_int("MAX_SECONDS", 2400)  # 0 explicitly removes the cap
    year_start = env_int("YEAR_START", 1989)
    year_end = env_int("YEAR_END", datetime.now(timezone.utc).year)

    bulletins = discover_bulletins(year_start, year_end)
    done = existing_ids(CC)
    ok = skip = fail = 0
    discovered = 0
    seen_sources, seen_contents = set(), set()
    for record_path in (ROOT / CC / "instruments").glob("*.json"):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if record.get("source_url"):
                seen_sources.add(_document_key(record["source_url"]))
            if record.get("text"):
                seen_contents.add(_content_fingerprint(record["text"]))
        except (OSError, ValueError, TypeError):
            continue

    for b in bulletins:
        if max_seconds and (time.time() - t_start) > max_seconds:
            log.info("time cap reached")
            break
        if max_new and ok >= max_new:
            log.info("max_new reached %s", max_new)
            break
        year, num = int(b["year"]), str(b["num"])
        try:
            docs = docs_for_bulletin(year, num)
        except Exception as exc:
            log.warning("docs fail %s/%s: %s", year, num, exc)
            continue
        log.info("bulletin %s/%s docs=%s", year, num, len(docs))
        for doc in docs:
            if max_seconds and (time.time() - t_start) > max_seconds:
                break
            if max_new and ok >= max_new:
                break
            stem, html_u, pdf_u = doc_urls(doc, year, num)
            if not stem:
                fail += 1
                continue
            discovered += 1
            ident = f"bopa-{year}-{safe_bulletin_slug(num)}-{stem}"
            rid = slug_id(CC, ident)
            if rid in done or _document_key(html_u) in seen_sources:
                skip += 1
                continue
            title = decode_sumari(doc.get("sumari")) or stem
            text, src, method = fetch_doc_text(html_u, pdf_u)
            if not text or len(text) < 80:
                fail += 1
                log_failure(
                    CC,
                    {
                        "identifier": ident,
                        "source_url": html_u,
                        "status": "failed",
                        "reason": method or "empty_text",
                    },
                )
                continue
            fingerprint = _content_fingerprint(text)
            if fingerprint in seen_contents:
                skip += 1
                continue
            date = iso_date(doc.get("dataPublicacioButlleti") or doc.get("dataArticle") or b.get("dataPublicacio"))
            meta = {
                "discovery": {
                    "method": "bopa_azure_api",
                    "year": year,
                    "num": num,
                    "isExtra": b.get("isExtra"),
                    "organisme": doc.get("organisme"),
                    "organismePare": doc.get("organismePare"),
                    "tema": doc.get("tema"),
                    "fileType": doc.get("fileType"),
                },
                "fetch_method": method,
            }
            if save_instrument(
                cc=CC,
                country=COUNTRY,
                language=LANG,
                ident=ident,
                title=title[:500],
                text=text,
                source_url=src,
                source_type=SOURCE_TYPE,
                license_text=LICENSE,
                collector="collect_ad.py",
                date=date,
                article_re=ART,
                extra_meta=meta,
            ):
                ok += 1
                done.add(rid)
                seen_sources.add(_document_key(src))
                seen_contents.add(fingerprint)
                append_catalog(
                    CC,
                    {
                        "id": rid,
                        "identifier": ident,
                        "year": year,
                        "num": num,
                        "html": html_u,
                        "pdf": pdf_u,
                        "title": title[:240],
                    },
                )
                if ok % 25 == 0:
                    log.info("progress ok=%s skip=%s fail=%s", ok, skip, fail)
                    write_summary(
                        CC,
                        country=COUNTRY,
                        source="BOPA — Butlletí Oficial del Principat d'Andorra",
                        source_urls=[
                            "https://www.bopa.ad/",
                            "https://documents.bopa.ad/bopa-documents",
                            "https://bopaazurefunctions.azurewebsites.net",
                        ],
                        license_text=LICENSE,
                        discovered=discovered,
                        fetched=ok,
                        skipped=skip,
                        failed=fail,
                        coverage="catalog-backed incomplete",
                        notes="Official BOPA API + documents.bopa.ad HTML/PDF. No WAF bypass.",
                        last_run=utcnow(),
                    )
            else:
                fail += 1

    # Complement document-level API/HTML discovery with upstream official PDF issues.
    for ident, url in discover_pdf_issues():
        if (max_new and ok >= max_new) or (max_seconds and time.time() - t_start > max_seconds):
            break
        discovered += 1
        rid = slug_id(CC, ident)
        if rid in done or _document_key(url) in seen_sources:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=True, min_text=120)
        text = got.get("text") or ""
        if got.get("status") != "success" or len(text) < 120:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        fingerprint = _content_fingerprint(text)
        if fingerprint in seen_contents:
            skip += 1
            continue
        title = next((line.strip()[:240] for line in text.splitlines() if len(line.strip()) > 15), ident)
        if save_instrument(cc=CC, country=COUNTRY, language=LANG, ident=ident,
                           title=title, text=text, source_url=url, source_type="bopa_ad",
                           license_text=LICENSE, collector="collect_ad.py", article_re=ART,
                           extra_meta={"discovery": {"method": "official_pdf_cdx"}, "fetch_method": got.get("method")}):
            ok += 1
            done.add(rid)
            seen_sources.add(_document_key(url))
            seen_contents.add(fingerprint)
        else:
            fail += 1

    write_summary(
        CC,
        country=COUNTRY,
        source="BOPA — Butlletí Oficial del Principat d'Andorra",
        source_urls=[
            "https://www.bopa.ad/",
            "https://documents.bopa.ad/bopa-documents",
            "https://bopaazurefunctions.azurewebsites.net",
        ],
        license_text=LICENSE,
        discovered=discovered or (ok + skip + fail),
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete",
        notes=(
            "Optional configured BOPA GetMonthButlletins + GetDocumentsByBOPA plus official PDF CDX discovery; "
            "bodies from documents.bopa.ad html then pdf. Wayback of official URLs only if live fails. "
            "Not portaljuridicandorra.ad (consolidations) in this pass. Not legal advice."
        ),
        last_run=utcnow(),
        extra=f"started {t0}; bulletins={len(bulletins)}; YEAR_START={year_start} YEAR_END={year_end}",
    )
    log.info("done ok=%s skip=%s fail=%s bulletins=%s", ok, skip, fail, len(bulletins))


if __name__ == "__main__":
    main()
