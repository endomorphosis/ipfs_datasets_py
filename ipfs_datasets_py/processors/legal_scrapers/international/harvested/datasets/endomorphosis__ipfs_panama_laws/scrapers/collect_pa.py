#!/usr/bin/env python3
"""Panama: Gaceta Oficial (gacetaoficial.gob.pa) PDFs via live + Wayback of official hosts.

Official only:
  https://www.gacetaoficial.gob.pa/  (pdfTemp / gacetas / sites/default/files)
No vLex / La Ley. Prefer text-layer PDFs; Spanish OCR on moderate scans; skip oversized.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    ROOT,
    base_record,
    existing_ids,
    log_failure,
    slug_id,
    utcnow,
    write_instrument,
    write_summary,
)
from world_lib import cdx_urls, env_int, setup_log
import archive_fallbacks as af
from pdf_extract_lib import extract_pdf_text, honest_split

CC, COUNTRY, LANG = "pa", "Panama", "es"
SOURCE_TYPE = "gaceta_oficial_pa"
LICENSE = (
    "Gaceta Oficial de la República de Panamá (gacetaoficial.gob.pa). "
    "Authentic gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.gacetaoficial.gob.pa/)"
ART = re.compile(r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+[\d]+[º°o.]?)\b")
log = logging.getLogger("pa")

OFFICIAL_HOSTS = ("gacetaoficial.gob.pa", "www.gacetaoficial.gob.pa")
os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")


def is_thin_es(text: str) -> bool:
    if not text or len(text) < 120:
        return True
    if text.lstrip().startswith("%PDF") or "endobj" in text[:200]:
        return True
    sample = text[:8000]
    letters = sum(ch.isalpha() for ch in sample)
    if letters < 200:
        return True
    if sample.count(" ") > letters * 2.2:
        return True
    singles = len(re.findall(r"(?m)^\s*[A-Za-zÁÉÍÓÚÑáéíóúñ]\s*$", sample))
    if singles > 40 and singles > letters * 0.2:
        return True
    low = sample.lower()
    if letters >= 400:
        return False
    return not any(
        k in low
        for k in (
            "gaceta",
            "artículo",
            "articulo",
            "decreto",
            "ley ",
            "resoluci",
            "república",
            "republica",
            "asamblea",
            "panamá",
            "panama",
        )
    )


def _norm_url(url: str) -> str:
    url = (url or "").strip().split("#")[0].split("?")[0]
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    # Fix CDX https://host:80/ quirk
    url = re.sub(r"https://([^/]+):80/", r"https://\1/", url)
    url = re.sub(r"http://([^/]+):80/", r"http://\1/", url)
    # Prefer https www
    url = url.replace("http://www.gacetaoficial.gob.pa/", "https://www.gacetaoficial.gob.pa/")
    url = url.replace("http://gacetaoficial.gob.pa/", "https://www.gacetaoficial.gob.pa/")
    url = url.replace("https://gacetaoficial.gob.pa/", "https://www.gacetaoficial.gob.pa/")
    # Collapse double slashes in path (keep scheme)
    url = re.sub(r"(https://www\.gacetaoficial\.gob\.pa)/+", r"\1/", url)
    return url


def _is_official_pdf(url: str) -> bool:
    low = url.lower()
    if ".pdf" not in low:
        return False
    if not any(h in low for h in ("gacetaoficial.gob.pa",)):
        return False
    # junk / non-instrument noise from CDX
    if any(
        x in low
        for x in (
            ".pdfromero",
            "/user/",
            "/theme/",
            "favicon",
            ".jpg",
            ".png",
            "wp-content",
        )
    ):
        return False
    # Prefer gazette-looking paths
    if any(
        p in low
        for p in (
            "/pdftemp/",
            "/gacetas/",
            "/sites/default/files/",
            "gacetano_",
            "gaceta_no",
            "gaceta-",
        )
    ):
        return True
    # Allow other host PDFs that look like instruments
    stem = Path(unquote(urlparse(url).path)).stem.lower()
    return bool(re.search(r"gaceta|decreto|ley|resoluci|ley_|go[_-]?\d", stem))


def http_cdx(prefix: str, *, limit: int = 200) -> list[dict]:
    """HTTP Wayback CDX with length field."""
    parts = [
        f"url={urllib.parse.quote(prefix)}",
        "output=json",
        "fl=original,timestamp,mimetype,statuscode,length",
        f"limit={limit}",
        "collapse=urlkey",
        "matchType=prefix",
    ]
    api = "http://web.archive.org/cdx/search/cdx?" + "&".join(parts)
    try:
        req = urllib.request.Request(api, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:
        log.info("cdx fail %s: %s", prefix, exc)
        return []
    if not data:
        return []
    rows = data[1:] if data[0] and data[0][0] == "original" else data
    out = []
    for row in rows:
        if len(row) < 2:
            continue
        out.append(
            {
                "original": row[0],
                "timestamp": row[1],
                "mimetype": row[2] if len(row) > 2 else "",
                "statuscode": row[3] if len(row) > 3 else "",
                "length": row[4] if len(row) > 4 else "0",
            }
        )
    return out


def discover() -> list[tuple[str, str, str | None, int]]:
    """Return (ident, url, wayback_ts, length) quality-sorted."""
    items: list[tuple[str, str, str | None, int]] = []
    seen: set[str] = set()
    cdx_limit = env_int("CDX_LIMIT", 1200)

    def add(url: str, ts: str | None = None, length: int = 0):
        url = _norm_url(url)
        if not _is_official_pdf(url):
            return
        key = re.sub(r"^https?://(www\.)?", "", url.lower())
        if key in seen:
            return
        seen.add(key)
        path = unquote(urlparse(url).path)
        stem = Path(path).stem[:160] or re.sub(r"\W+", "-", url)[-80:]
        ident = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("_")[:140] or "gaceta"
        items.append((ident, url, ts, length))

    prefixes = [
        "www.gacetaoficial.gob.pa/pdfTemp/",
        "gacetaoficial.gob.pa/pdfTemp/",
        "www.gacetaoficial.gob.pa/gacetas/",
        "gacetaoficial.gob.pa/gacetas/",
        "www.gacetaoficial.gob.pa/sites/default/files/",
    ]
    # Split budget across prefixes
    per = max(80, cdx_limit // max(1, len(prefixes) - 1))
    for i, prefix in enumerate(prefixes):
        lim = cdx_limit if i == 0 else per
        hits = http_cdx(prefix, limit=lim)
        if not hits:
            # fallback to shared CDX helper
            hits = cdx_urls(prefix, limit=lim, match_type="prefix")
        for h in hits:
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            add(h.get("original") or "", h.get("timestamp"), length)

    def rank(it):
        ident, url, ts, length = it
        low = (ident + " " + url).lower()
        # Prefer GacetaNo_* named gazettes and smaller files (text layers more likely)
        score = 0
        if "gacetano_" in low or re.search(r"gaceta.?no", low):
            score -= 50
        if "/gacetas/" in low:
            score -= 20
        if length and 50_000 < length < 2_000_000:
            score -= 30
        elif length and length < 5_000_000:
            score -= 10
        elif length and length >= 8_000_000:
            score += 80
        # Prefer more recent-looking years in name
        ym = re.search(r"(20\d{2})", ident)
        if ym:
            score -= int(ym.group(1)) - 2000
        return (score, length or 10**9, ident)

    items.sort(key=rank)
    log.info("catalog %s unique official PDFs", len(items))
    return items


def fetch_pdf(url: str, ts: str | None) -> tuple[bytes, str]:
    """Live first, then Wayback of the same official URL."""
    # live
    try:
        import requests
        from requests.packages.urllib3.exceptions import InsecureRequestWarning

        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        headers = {"User-Agent": UA, "Accept": "application/pdf,*/*"}
        for verify in (True, False):
            try:
                time.sleep(0.15)
                r = requests.get(url, timeout=(20, 120), headers=headers, verify=verify, allow_redirects=True)
                body = r.content or b""
                if r.status_code == 200 and body[:4] == b"%PDF":
                    return body, "http_pdf"
            except Exception:
                continue
    except Exception:
        pass
    # wayback
    try:
        w = af.get_wayback_content(url, timestamp=ts)
        if w.get("status") == "success":
            raw_b = w.get("content") or b""
            if isinstance(raw_b, bytes) and raw_b[:4] == b"%PDF":
                return raw_b, "wayback_pdf"
            raw_t = w.get("text") or ""
            if raw_t.lstrip().startswith("%PDF"):
                return raw_t.encode("latin-1", "replace"), "wayback_pdf"
    except Exception:
        pass
    return b"", "fail"


def first_title(text: str, fallback: str) -> str:
    for line in (text or "").splitlines():
        s = line.strip()
        if len(s) < 12 or s.lower().startswith("just a moment"):
            continue
        if re.search(r"(?i)gaceta\s+oficial|rep[uú]blica|constituci|ley |decreto|resoluci|asamblea", s):
            return s[:240]
        if len(s) > 24:
            return s[:240]
    return fallback[:240]


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 280)
    max_seconds = env_int("MAX_SECONDS", 5400)
    ocr_pages = env_int("OCR_PAGES", 8)
    max_bytes = env_int("MAX_PDF_BYTES", 5_000_000)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0

    for ident, url, ts, length in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        if length and length > max_bytes:
            skip += 1
            continue
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        raw, method = fetch_pdf(url, ts)
        if not raw:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "fetch_fail"})
            continue
        if len(raw) > int(max_bytes * 1.25):
            skip += 1
            log.info("skip oversized %s bytes=%s", ident[:60], len(raw))
            continue
        text, how, pages = extract_pdf_text(
            raw, enable_ocr=True, ocr_lang="spa", ocr_max_pages=ocr_pages
        )
        if how.startswith("ocr"):
            ocr_used += 1
        if not text or len(text) < 120 or is_thin_es(text):
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": ident,
                    "source_url": url,
                    "reason": f"thin:{how}",
                    "chars": len(text or ""),
                },
            )
            continue
        docs, kind = honest_split(CC, text, rid, url)
        if len(docs) < 2:
            matches = list(ART.finditer(text))
            if len(matches) >= 2:
                docs = []
                for i, m in enumerate(matches):
                    start = m.start()
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                    chunk = text[start:end].strip()
                    if len(chunk) < 20:
                        continue
                    num = re.sub(r"\s+", " ", m.group(1)).strip()
                    aid = re.sub(r"[^a-zA-Z0-9-]+", "-", num.lower()).strip("-")[:80]
                    docs.append(
                        {
                            "id": f"{rid}-{aid}"[:180],
                            "title": chunk.split("\n", 1)[0][:200],
                            "text": chunk,
                            "date_filed": None,
                            "document_number": num,
                            "source_url": url,
                            "record_type": "article",
                            "article_number": num,
                            "law_identifier": ident,
                            "metadata": {
                                "text_extraction": {"source": "ocr_or_pdf", "backend": how}
                            },
                        }
                    )
                kind = "articulo_re"

        title = first_title(text, ident)
        date = None
        m = re.search(r"(20\d{2})[_-](\d{2})[_-](\d{2})", ident)
        if m:
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            m = re.search(r"(\d{2})[_-](\d{2})[_-](20\d{2})", ident)
            if m:
                date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            else:
                m = re.search(r"(20\d{2})(\d{2})(\d{2})", ident)
                if m:
                    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

        rec = base_record(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_pa.py",
            date=date,
            documents=docs,
            extra_meta={
                "fetch_method": method,
                "extract_method": how,
                "pages": pages,
                "pdf_bytes": len(raw),
                "article_split": {"method": kind, "count": len(docs)},
                "wayback_ts": ts,
                "official_hosts": list(OFFICIAL_HOSTS),
            },
        )
        write_instrument(CC, rec)
        ok += 1
        done.add(rid)
        log.info(
            "ok %s method=%s extract=%s arts=%s chars=%s",
            ident[:70],
            method,
            how,
            len(docs),
            len(text),
        )

    write_summary(
        CC,
        country=COUNTRY,
        source="Gaceta Oficial de Panamá",
        source_urls=["https://www.gacetaoficial.gob.pa/"],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete (live + Wayback of official Gaceta PDFs; OCR on scans)",
        notes=(
            f"Official Gaceta PDFs only (pdfTemp/gacetas). OCR used on {ocr_used} instruments. "
            f"Skipped oversized PDFs >{max_bytes} bytes. Not vLex/La Ley. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
