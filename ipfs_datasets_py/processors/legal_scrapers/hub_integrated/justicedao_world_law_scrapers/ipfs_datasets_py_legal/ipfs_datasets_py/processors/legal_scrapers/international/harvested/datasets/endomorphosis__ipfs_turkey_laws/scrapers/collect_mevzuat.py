#!/usr/bin/env python3
"""Turkey: Kanunlar from the official T.C. Mevzuat Bilgi Sistemi.

Official sources only:
  - https://www.mevzuat.gov.tr/  (Cumhurbaşkanlığı Mevzuat Bilgi Sistemi)
  - Bedesten JSON API used by the official portal:
    https://bedesten.adalet.gov.tr/mevzuat  (Adalet Bakanlığı / UYAP)

Kanunlar (MevzuatTur=KANUN) first. Does not use kazancı, lexpera, or other
commercial databases. No WAF bypass. mevzuat.gov.tr TLS intermediate may be
missing in this environment; texts are taken from the official Bedesten
getDocument payload whose canonical URL is mevzuat.gov.tr.

On HTTP 429 from Bedesten, official mevzuat.gov.tr URLs are fetched via
archive_fallbacks (Common Crawl, then Wayback, then archive.is).
"""
from __future__ import annotations

import base64
import json
import logging
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "tr"
COUNTRY = "Turkey"
SOURCE_TYPE = "mevzuat_gov_tr"
LICENSE = (
    "Official legislative texts of the Republic of Türkiye published by the "
    "Mevzuat Bilgi Sistemi (mevzuat.gov.tr / Adalet Bakanlığı Bedesten). "
    "Official documents of state bodies are not copyright-protected under "
    "Turkish Law no. 5846 art. 31 (official texts). The authentic Resmî "
    "Gazete text prevails. Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.mevzuat.gov.tr/"
BEDESTEN = "https://bedesten.adalet.gov.tr/mevzuat"
PORTAL = "https://www.mevzuat.gov.tr"
WORKERS = 2
SLEEP = 0.85
PAGE = 20
log = logging.getLogger("tr")
_done_lock = threading.Lock()

ART_TR = re.compile(
    r"(?im)^\s*((?:MADDE|Madde|GEÇİCİ MADDE|Geçici Madde|EK MADDE|Ek Madde)\s+"
    r"\d+[A-Za-z]?)\b"
)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def split_custom(pattern: re.Pattern, text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    if not text or len(text) < 40:
        return []
    matches = list(pattern.finditer(text))
    if len(matches) < 2:
        return []
    docs = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        heading = chunk.split("\n", 1)[0][:200]
        docs.append({
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
        if len(docs) >= 4000:
            break
    return docs


def bedesten_post(path: str, payload: dict, retries: int = 6) -> dict:
    url = f"{BEDESTEN}{path}"
    last = None
    for attempt in range(1, retries + 1):
        try:
            if SLEEP:
                time.sleep(SLEEP)
            sess = get_session(UA, pool=WORKERS)
            r = sess.post(
                url, json=payload, timeout=(20, 90),
                headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": UA},
            )
            if r.status_code == 429:
                last = r
                if attempt < retries:
                    time.sleep(min(45, 4 * (2 ** (attempt - 1))))
                    continue
                raise RuntimeError(f"HTTP 429 {url} {r.text[:200]}")
            if r.status_code in (500, 502, 503, 504) and attempt < retries:
                time.sleep(min(25, 2 ** attempt))
                last = r
                continue
            if r.status_code != 200:
                last = r
                if attempt < retries:
                    time.sleep(1.5 * attempt)
                    continue
                raise RuntimeError(f"HTTP {r.status_code} {url} {r.text[:200]}")
            js = r.json()
            meta = js.get("metadata") or {}
            if str(meta.get("FMTY") or "").upper() == "ERROR":
                raise RuntimeError(f"bedesten error {url}: {meta.get('FMTE') or meta}")
            return js
        except RuntimeError:
            raise
        except Exception as exc:
            last = exc
            time.sleep(min(20, 1.5 * attempt))
    raise RuntimeError(f"POST failed {url}: {last}")


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog_kanun.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 200:
        return []
    items = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def save_catalog(items: list[dict]) -> None:
    body = "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items)
    atomic_write(catalog_path(), body)


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 900:
        log.info("resume catalog n=%s", len(existing))
        return existing
    items: list[dict] = []
    seen: set[str] = set()
    page = 1
    expected = None
    while page <= 80:
        payload = {
            "data": {
                "pageSize": PAGE,
                "pageNumber": page,
                "mevzuatTurList": ["KANUN"],
                "sortFields": ["MEVZUAT_NO"],
                "sortDirection": "desc",
            },
            "applicationName": "UyapMevzuat",
            "paging": True,
        }
        data = bedesten_post("/searchDocuments", payload)
        block = data.get("data") or {}
        batch = block.get("mevzuatList") or []
        if expected is None:
            expected = block.get("total")
            log.info("catalog expected=%s", expected)
        newc = 0
        for row in batch:
            mid = str(row.get("mevzuatId") or "")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            url = row.get("url") or (
                f"{PORTAL}/mevzuat?MevzuatNo={row.get('mevzuatNo')}"
                f"&MevzuatTur=1&MevzuatTertip={row.get('mevzuatTertip') or 5}"
            )
            items.append({
                "mevzuatId": mid,
                "mevzuatNo": row.get("mevzuatNo"),
                "mevzuatAdi": (row.get("mevzuatAdi") or "").strip(),
                "mevzuatTertip": row.get("mevzuatTertip") or 5,
                "resmiGazeteTarihi": row.get("resmiGazeteTarihi"),
                "resmiGazeteSayisi": row.get("resmiGazeteSayisi"),
                "url": url,
            })
            newc += 1
        log.info("catalog page=%s batch=%s new=%s total=%s", page, len(batch), newc, len(items))
        if not batch:
            break
        page += 1
        if expected and len(items) >= int(expected):
            break
        if len(batch) < PAGE:
            break
    save_catalog(items)
    log.info("catalog done n=%s expected=%s", len(items), expected)
    return items


def decode_html(b64: str) -> str:
    if not b64:
        return ""
    raw = base64.b64decode(b64)
    for enc in ("windows-1254", "utf-8", "latin-5", "cp1254"):
        try:
            html = raw.decode(enc)
            if html:
                return html
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


def pdf_to_text(raw: bytes) -> str:
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw)
            tmp.flush()
            proc = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                check=False, capture_output=True, timeout=240,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.info("pdftotext fail: %s", exc)
    return ""


def looks_like_kanun(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    compact = re.sub(r"\s+", " ", text)
    if re.search(r"(?i)\b(?:madde|geçici madde|ek madde)\s+\d+", compact):
        return True
    if re.search(r"(?i)kanun\s+numaras[ıi]", compact):
        return True
    return False


def official_urls(it: dict) -> list[str]:
    no = it.get("mevzuatNo")
    tertip = it.get("mevzuatTertip") or 5
    portal_url = it.get("url") or (
        f"{PORTAL}/mevzuat?MevzuatNo={no}&MevzuatTur=1&MevzuatTertip={tertip}"
    )
    urls = [
        f"{PORTAL}/MevzuatMetin/1.{tertip}.{no}.pdf",
        f"http://www.mevzuat.gov.tr/MevzuatMetin/1.{tertip}.{no}.pdf",
        f"{PORTAL}/anasayfa/MevzuatFihristDetayIframe?MevzuatTur=1&MevzuatTertip={tertip}&MevzuatNo={no}",
        f"{PORTAL}/File/GeneratePdf?mevzuatNo={no}&mevzuatTur=Kanun&mevzuatTertip={tertip}",
        portal_url,
    ]
    seen = set()
    out = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def text_from_archive_result(res: dict) -> str:
    body = res.get("content") or b""
    if isinstance(body, (bytes, bytearray)) and body[:4] == b"%PDF":
        return pdf_to_text(bytes(body))
    ctype = (res.get("content_type") or "").lower()
    if "pdf" in ctype and isinstance(body, (bytes, bytearray)):
        return pdf_to_text(bytes(body))
    html = res.get("text") or ""
    if not html and isinstance(body, (bytes, bytearray)) and body:
        for enc in ("utf-8", "windows-1254", "latin-5", "cp1254"):
            try:
                html = body.decode(enc)
                break
            except Exception:
                continue
        else:
            html = body.decode("utf-8", "replace")
    if not html:
        return ""
    if af.is_challenge(html, int(res.get("http_status") or 200)):
        return ""
    return html_to_text(html)


def fetch_from_archives(it: dict) -> tuple[str, dict]:
    """CC then Wayback then archive.is of official mevzuat.gov.tr URLs."""
    errors = []
    for url in official_urls(it):
        try:
            res = af.fetch_with_fallbacks(
                url,
                try_archive_is=True,
                try_http=False,
                try_cc=True,
            )
        except Exception as exc:
            errors.append(f"{url}:{exc}")
            continue
        if res.get("status") != "success":
            errors.append(f"{url}:{res.get('error')}")
            continue
        text = text_from_archive_result(res)
        if looks_like_kanun(text):
            meta = {
                "archive_method": res.get("method"),
                "archive_url": res.get("wayback_url") or res.get("archive_url") or url,
                "official_url_archived": url,
            }
            return text, meta
        errors.append(f"{url}:not_kanun_text len={len(text or '')} method={res.get('method')}")
    return "", {"archive_errors": errors[:12]}


def write_law(it: dict, rid: str, ident: str, text: str, source_url: str, extra_meta: dict) -> None:
    title = it.get("mevzuatAdi") or f"Kanun {it.get('mevzuatNo')}"
    date = iso_date((it.get("resmiGazeteTarihi") or "")[:10] if it.get("resmiGazeteTarihi") else None)
    docs = split_custom(ART_TR, text, rid, source_url, date)
    if not docs:
        docs = split_articles(text, rid, source_url, date)
    no = it.get("mevzuatNo")
    mid = str(it.get("mevzuatId") or "")
    tertip = it.get("mevzuatTertip") or 5
    rec = base_record(
        cc=CC, country=COUNTRY, language="tr", ident=ident, title=title, text=text,
        source_url=source_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_mevzuat.py", date=date,
        official_identifier=f"{no}" if no is not None else mid,
        document_type="statute", law_status="current", is_current=True, documents=docs,
        extra_meta={
            "mevzuat_no": no,
            "mevzuat_tertip": tertip,
            "resmi_gazete_sayisi": it.get("resmiGazeteSayisi"),
            "pdf_url": f"{PORTAL}/MevzuatMetin/1.{tertip}.{no}.pdf",
            **extra_meta,
        },
        extra_fields={
            "citation": f"{no} sayılı {title}" if no is not None else title,
            "publication_date": date,
            "date_issued": date,
        },
    )
    rec["id"] = rid
    write_instrument(CC, rec)


def choose_ident(it: dict, done: set[str]) -> str:
    """Prefer tr-kanun-{no}; if that id is a different tertip/mevzuatId, qualify."""
    mid = str(it.get("mevzuatId") or "")
    no = it.get("mevzuatNo")
    tertip = it.get("mevzuatTertip") or 5
    if no is None:
        return f"tr-mevzuat-{mid}"
    primary = f"tr-kanun-{no}"
    rid = slug_id(CC, primary)
    if rid not in done:
        return primary
    path = ROOT / CC / "instruments" / f"{rid}.json"
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        meta = rec.get("metadata") or {}
        have_mid = str((meta.get("discovery") or {}).get("mevzuat_id") or "")
        have_tertip = meta.get("mevzuat_tertip")
        if have_mid == mid or (have_tertip is not None and have_tertip == tertip):
            return primary
    except Exception:
        return primary
    return f"tr-kanun-{no}-t{tertip}"


def fetch_one(it: dict, done: set[str]) -> str:
    mid = str(it.get("mevzuatId") or "")
    no = it.get("mevzuatNo")
    ident = choose_ident(it, done)
    rid = slug_id(CC, ident)
    with _done_lock:
        if rid in done:
            return "skip"
    source_url = it.get("url") or f"{PORTAL}/mevzuat?MevzuatNo={no}&MevzuatTur=1&MevzuatTertip=5"
    live_err = None
    try:
        data = bedesten_post("/getDocument", {"data": {"mevzuatId": mid}, "applicationName": "UyapMevzuat"})
        block = data.get("data") or {}
        html = decode_html(block.get("content") or "")
        text = html_to_text(html)
        if text and looks_like_kanun(text):
            write_law(it, rid, ident, text, source_url, extra_meta={
                "discovery": {"method": "bedesten_getDocument", "mevzuat_id": mid},
            })
            with _done_lock:
                done.add(rid)
            return "ok"
        live_err = "empty_or_not_kanun_text"
    except Exception as exc:
        live_err = repr(exc)
        log.info("bedesten fail %s %s", rid, live_err[:180])

    is_429 = live_err and ("429" in str(live_err) or "Too Many Requests" in str(live_err))
    # Archives of official URLs: required on 429; also used for other live misses.
    text, ameta = fetch_from_archives(it)
    if text and looks_like_kanun(text):
        write_law(it, rid, ident, text, source_url, extra_meta={
            "discovery": {
                "method": "archive_fallback_of_official",
                "mevzuat_id": mid,
                "live_error": (live_err or "")[:300],
                "http_429": bool(is_429),
                **{k: v for k, v in ameta.items() if k != "archive_errors"},
            },
        })
        with _done_lock:
            done.add(rid)
        return "ok"
    log_failure(CC, {
        "id": rid, "url": source_url, "status": "failed",
        "reason": f"live={live_err}; archive={ameta.get('archive_errors') or ameta}",
    })
    return "fail"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    counters = {"ok": 0, "skip": 0, "fail": 0}
    source_urls = [
        "https://www.mevzuat.gov.tr/",
        "https://bedesten.adalet.gov.tr/mevzuat/searchDocuments",
        "https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?MevzuatTur=1&MevzuatTertip=5",
    ]
    notes = (
        "In-force Kanunlar from the official Mevzuat Bilgi Sistemi via the "
        "Adalet Bakanlığı Bedesten JSON API (mevzuatTurList=KANUN). Canonical "
        "source_url is mevzuat.gov.tr. On HTTP 429, official URLs are filled "
        "via archive_fallbacks (Common Crawl then Wayback then archive.is). "
        "Yönetmelik/tebliğ/KHK out of scope. Not kazancı/lexpera. Authentic "
        "Resmî Gazete prevails."
    )

    def write_progress(coverage: str, extra: str = ""):
        write_summary(
            CC, country=COUNTRY,
            source="T.C. Mevzuat Bilgi Sistemi (mevzuat.gov.tr / Adalet Bakanlığı)",
            source_urls=source_urls, license_text=LICENSE,
            discovered=len(items), fetched=counters["ok"], skipped=counters["skip"],
            failed=counters["fail"], coverage=coverage, notes=notes + extra,
        )

    done = existing_ids(CC)
    log.info("queue kanun=%s already_done=%s workers=%s", len(items), len(done), WORKERS)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in items]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            counters[st] = counters.get(st, 0) + 1
            if n % 25 == 0 or n == len(items):
                n_json = len(existing_ids(CC))
                log.info(
                    "progress %s/%s ok=%s skip=%s fail=%s instruments=%s",
                    n, len(items), counters["ok"], counters["skip"], counters["fail"], n_json,
                )
                cov = "full" if counters["fail"] == 0 and counters["ok"] + counters["skip"] >= len(items) else "catalog-backed incomplete"
                write_progress(cov)
    cov = "full" if counters["fail"] == 0 and counters["ok"] + counters["skip"] >= len(items) else "catalog-backed incomplete"
    write_progress(cov, extra=f" Started {t0}.")
    log.info("done ok=%s skip=%s fail=%s coverage=%s instruments=%s",
             counters["ok"], counters["skip"], counters["fail"], cov, len(existing_ids(CC)))


if __name__ == "__main__":
    main()
