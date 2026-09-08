#!/usr/bin/env python3
"""Russia: official pravo.gov.ru / publication.pravo.gov.ru only.

Born-digital texts from IPS эталонный банк (pravo.gov.ru/proxy/ips HTML/XML),
federal laws / constitutional laws / Constitution / codes first.

publication.pravo.gov.ru PDFs are ABBYY image scans (CCITTFaxDecode, no text
layer). CoS will not take OCR of those PDFs — they are catalogued and skipped.

Does not use ConsultantPlus, Garant, or other commercial DBs.
API help: http://publication.pravo.gov.ru/help
  GET /api/PublicBlocks/  GET /api/Documents  GET /api/Document
Open data CSV (metadata only, last 30/90/360 days): /opendata/Index
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as archives

CC = "ru"
COUNTRY = "Russia"
SOURCE_TYPE = "pravo_gov_ru_ips"
LICENSE = (
    "Official documents of state bodies, including laws and other normative acts, "
    "are not objects of copyright (Civil Code of the Russian Federation art. 1259(6)). "
    "Texts from the Official Internet Portal of Legal Information "
    "(pravo.gov.ru / publication.pravo.gov.ru). Not legal advice; the official "
    "publication prevails."
)
UA = DEFAULT_UA + " source=http://pravo.gov.ru/proxy/ips/"
PUB_BASE = "http://publication.pravo.gov.ru"
IPS_BASE = "http://pravo.gov.ru/proxy/ips/"
WORKERS = int(os.environ.get("RU_WORKERS", "4"))
SLEEP = float(os.environ.get("RU_SLEEP", "0.35"))
LSTSIZE = 200
MAX_DOCS = int(os.environ.get("RU_MAX_DOCS", "0") or "0")  # 0 = no cap
log = logging.getLogger("ru")

# IPS classifier short ids (hclassif nclassif=3, bank cd00000)
A3_CONSTITUTION = "102000488"
A3_FKZ = "102000506"
A3_FZ = "102000505"
A3_CODE = "102000486"

# publication.pravo.gov.ru documentType GUIDs (catalog only; PDFs not ingested)
TYPE_CONST = "8fb60238-9fee-4a1b-9534-6d99ad0ceff0"
TYPE_AMEND = "e0c56da5-17f1-40ac-a10f-8a9a1cee0c4e"
TYPE_FKZ = "93273da3-3133-4acf-96c2-4adc1ae70e19"
TYPE_FZ = "82a8bf1c-3bc7-47ed-827f-7affd43a7f27"

ART_RU = re.compile(
    r"(?im)^\s*((?:Статья|Ст\.)\s+\d+(?:\.\d+)*[а-яa-z]?)\b"
)
DATE_RU = re.compile(r"от\s+(\d{2}\.\d{2}\.\d{4})")
NUM_RU = re.compile(r"№\s*([0-9A-Za-zА-Яа-яIVXLC.\-]+(?:-[А-ЯA-Z]+)?)")
CHECK_ND = re.compile(r'name="check_(\d+)"')
LIST_SIZE_RE = re.compile(r"top\.listSize\s*=\s*(\d+)")
STATUS_RE = re.compile(r'tiny_italic_bold">\s*([^<]+)')
TITLE_A_RE = re.compile(r'<a id="link_\d+"[^>]*>\s*([^<]+)</a>', re.I)
SUB_RE = re.compile(r'<span class="bold">([^<]*)</span>')


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def decode_ips(raw: bytes) -> str:
    if not raw:
        return ""
    head = raw[:2500].lower()
    if b"windows-1251" in head or b"charset=windows-1251" in head:
        return raw.decode("cp1251", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", "replace")


def ips_html_to_text(html: str) -> str:
    if not html:
        return ""
    m = re.search(
        r'<div id="text_content"\s*>(.*)</div>\s*</div>',
        html, re.I | re.S,
    )
    blob = m.group(1) if m else html
    blob = re.sub(r"(?is)<title>.*?</title>", " ", blob)
    text = html_to_text(blob)
    text = re.sub(r"(?im)^\s*Complex\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def split_ru_articles(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_RU.finditer(text or ""))
    if len(matches) < 2:
        return []
    out = []
    seen = set()
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9а-яё]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        heading = chunk.split("\n", 1)[0][:200]
        out.append({
            "id": doc_id,
            "title": heading,
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "pravo_ips_html"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def map_status(label: str) -> tuple[str, bool]:
    s = (label or "").strip().lower()
    if "утратил" in s or "утратилa" in s:
        return "repealed", False
    if "не вступ" in s:
        return "future", False
    if "приостан" in s:
        return "suspended", False
    return "current", True


def parse_list_page(html: str) -> tuple[int, list[dict]]:
    expected = 0
    m = LIST_SIZE_RE.search(html or "")
    if m:
        expected = int(m.group(1))
    items = []
    chunks = re.split(r'<table class="list_elem', html or "")
    for ch in chunks[1:]:
        ndm = CHECK_ND.search(ch)
        if not ndm:
            continue
        nd = ndm.group(1)
        title_m = TITLE_A_RE.search(ch)
        title = re.sub(r"\s+", " ", (title_m.group(1) if title_m else "").strip())
        sub_m = SUB_RE.search(ch)
        subtitle = re.sub(r"\s+", " ", (sub_m.group(1) if sub_m else "").strip())
        st_m = STATUS_RE.search(ch)
        status_label = re.sub(r"\s+", " ", (st_m.group(1) if st_m else "").strip())
        items.append({
            "nd": nd,
            "title": title,
            "subtitle": subtitle,
            "status_label": status_label,
        })
    return expected, items


def ips_list(a3: str, start: int, lstsize: int = LSTSIZE) -> tuple[int, list[dict]]:
    params = {
        "list_itself": "",
        "bpas": "cd00000",
        "a3": a3,
        "a3type": "1",
        "sort": "7",
        "lstsize": str(lstsize),
        "start": str(start),
    }
    r = http_get(
        IPS_BASE, ua=UA, sleep=SLEEP, timeout=(20, 120), retries=5,
        params=params, headers={"Accept": "text/html, */*"}, allow_empty=True,
    )
    if r.status_code != 200 or not r.content:
        log.warning("ips list fail a3=%s start=%s status=%s", a3, start, r.status_code)
        return 0, []
    return parse_list_page(decode_ips(r.content))


def discover_ips(a3: str, kind: str) -> list[dict]:
    items: list[dict] = []
    seen = set()
    start = 0
    expected = None
    while start < 200000:
        exp, batch = ips_list(a3, start, LSTSIZE)
        if expected is None:
            expected = exp
            log.info("ips catalog kind=%s a3=%s expected=%s", kind, a3, expected)
        if not batch:
            break
        newc = 0
        for row in batch:
            nd = row.get("nd")
            if not nd or nd in seen:
                continue
            seen.add(nd)
            row = dict(row)
            row["kind"] = kind
            row["a3"] = a3
            items.append(row)
            append_catalog(CC, {"source": "ips", **row})
            newc += 1
        log.info("ips catalog kind=%s start=%s new=%s total=%s expected=%s",
                 kind, start, newc, len(items), expected)
        if expected and start + LSTSIZE >= expected:
            break
        if len(batch) < max(1, LSTSIZE // 4) and expected and len(items) >= expected:
            break
        start += LSTSIZE
        if expected and len(items) >= expected:
            break
    return items


def ips_text(nd: str) -> tuple[str, str, str]:
    """Return (text, url, method). method is live / wayback / common_crawl / fail."""
    url = f"{IPS_BASE}?doc_itself=&nd={nd}&page=1&rdk=0&link_id=0"
    r = http_get(
        url, ua=UA, sleep=SLEEP, timeout=(20, 180), retries=4,
        headers={"Accept": "text/html, */*"}, allow_empty=True,
    )
    if r.status_code == 200 and r.content and len(r.content) > 400:
        html = decode_ips(r.content)
        text = ips_html_to_text(html)
        if text and len(text) >= 80:
            return text, url, "live"
    # Wayback / Common Crawl of the official IPS URL only. No WAF bypass.
    try:
        res = archives.fetch_with_fallbacks(
            url, try_archive_is=False, try_http=False, try_cc=True,
        )
    except Exception as exc:
        log.warning("archive fallback nd=%s: %s", nd, exc)
        return "", url, "fail"
    if res.get("status") != "success":
        return "", url, "fail"
    raw = res.get("content") or b""
    html = res.get("text") or ""
    if raw and (not html or "windows-1251" in (html[:500].lower())):
        html = decode_ips(raw if isinstance(raw, (bytes, bytearray)) else html.encode("utf-8", "replace"))
    text = ips_html_to_text(html)
    method = res.get("method") or "archive"
    if text and len(text) >= 80:
        return text, res.get("wayback_url") or res.get("archive_url") or url, method
    return "", url, "fail"


def fetch_one(it: dict, done: set[str]) -> str:
    nd = str(it.get("nd") or "").strip()
    if not nd:
        return "fail"
    rid = slug_id(CC, f"ips-{nd}")
    if rid in done:
        return "skip"
    text, url, method = ips_text(nd)
    if not text or len(text) < 80:
        log_failure(CC, {
            "identifier": nd, "source_url": url, "status": "failed",
            "reason": "empty_ips",
        })
        return "fail"
    kind = it.get("kind") or "statute"
    title = it.get("subtitle") or it.get("title") or f"IPS {nd}"
    citation = it.get("title") or title
    if it.get("subtitle") and it.get("title"):
        title = it["subtitle"] if len(it["subtitle"]) > 8 else it["title"]
        citation = f"{it['title']}. {it['subtitle']}".strip(". ")
    dm = DATE_RU.search(it.get("title") or "")
    date = iso_date(dm.group(1)) if dm else None
    nm = NUM_RU.search(it.get("title") or "")
    official = (nm.group(1) if nm else None) or nd
    status_label = it.get("status_label") or ""
    law_status, is_current = map_status(status_label)
    docs = split_ru_articles(text, rid, url, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language="ru", ident=f"ips-{nd}", title=title, text=text,
        source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="ru-pravo-gov",
        official_identifier=official, document_type=kind,
        law_status=law_status, is_current=is_current, documents=docs, date=date,
        extra_meta={
            "discovery": {
                "method": "ips_list_itself",
                "catalog_identifier": nd,
                "seed_url": IPS_BASE,
                "a3": it.get("a3"),
            },
            "official_metadata": {
                "nd": nd,
                "ips_kind": kind,
                "status_label": status_label,
                "citation": citation,
                "text_backend": method,
            },
            "text_extraction": {"source": "official", "backend": f"pravo_ips_{method}"},
        },
        extra_fields={
            "canonical_title": citation or title,
            "citation": citation,
            "canonical_document_url": url,
            "information_url": url,
        },
    )
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def publication_catalog_counts() -> tuple[int, int, int]:
    """Reuse existing publication API catalog (image PDFs, not ingested)."""
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    n_fz = n_fkz = n_c = 0
    if not cat.exists():
        return 0, 0, 0
    with cat.open(encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("source") == "ips":
                continue
            tid = row.get("documentTypeId")
            if tid == TYPE_FZ:
                n_fz += 1
            elif tid == TYPE_FKZ:
                n_fkz += 1
            elif tid in {TYPE_CONST, TYPE_AMEND}:
                n_c += 1
    return n_c, n_fkz, n_fz


def main():
    setup()
    t0 = utcnow()
    done = existing_ids(CC)
    log.info("existing instruments %s", len(done))

    queues = [
        (A3_CONSTITUTION, "constitution"),
        (A3_FKZ, "statute"),  # federal constitutional laws
        (A3_CODE, "code"),
        (A3_FZ, "statute"),
    ]
    # Prefer constitutional instruments first, then codes, then FZ.
    items: list[dict] = []
    seen_nd = set()
    for a3, kind in queues:
        batch = discover_ips(a3, kind)
        # Re-tag FKZ distinctly for logging; document_type stays statute/code/constitution
        if a3 == A3_FKZ:
            for it in batch:
                it["kind"] = "statute"
                it["ips_class"] = "fkz"
        elif a3 == A3_FZ:
            for it in batch:
                it["ips_class"] = "fz"
        for it in batch:
            nd = it.get("nd")
            if nd in seen_nd:
                continue
            seen_nd.add(nd)
            items.append(it)
        if MAX_DOCS and len(items) >= MAX_DOCS:
            items = items[:MAX_DOCS]
            break

    log.info("discovered ips nds=%s (constitution/fkz/code/fz queues)", len(items))
    if MAX_DOCS:
        items = items[:MAX_DOCS]
        log.info("RU_MAX_DOCS cap -> %s", len(items))

    ok = skip = fail = 0
    # Sequential for constitution + FKZ + codes (small, first), then thread FZ.
    small = [it for it in items if it.get("a3") in {A3_CONSTITUTION, A3_FKZ, A3_CODE}]
    large = [it for it in items if it.get("a3") == A3_FZ]
    for it in small:
        st = fetch_one(it, done)
        if st == "ok":
            ok += 1
        elif st == "skip":
            skip += 1
        else:
            fail += 1
        if (ok + skip + fail) % 25 == 0:
            log.info("progress small ok=%s skip=%s fail=%s", ok, skip, fail)

    if large:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(fetch_one, it, done): it for it in large}
            n = 0
            for fut in as_completed(futs):
                n += 1
                try:
                    st = fut.result()
                except Exception as exc:
                    log.warning("fetch exc: %s", exc)
                    st = "fail"
                if st == "ok":
                    ok += 1
                elif st == "skip":
                    skip += 1
                else:
                    fail += 1
                if n % 50 == 0 or n == len(large):
                    log.info("progress fz %s/%s ok=%s skip=%s fail=%s",
                             n, len(large), ok, skip, fail)

    n_c, n_fkz, n_fz = publication_catalog_counts()
    source_urls = [
        "http://pravo.gov.ru/",
        "http://pravo.gov.ru/proxy/ips/",
        "http://publication.pravo.gov.ru/",
        "http://publication.pravo.gov.ru/help",
        "http://publication.pravo.gov.ru/api/PublicBlocks/",
        "http://publication.pravo.gov.ru/api/Documents",
        "http://publication.pravo.gov.ru/opendata/Index",
    ]
    n_json = len(list((ROOT / CC / "instruments").glob("*.json")))
    cov = "snapshot"
    if fail == 0 and items and ok + skip >= len(items) and n_json > 100:
        cov = "ips-consolidations snapshot"
    notes = (
        f"IPS эталонный банк born-digital HTML from pravo.gov.ru/proxy/ips "
        f"(list_itself a3 constitution={A3_CONSTITUTION} fkz={A3_FKZ} "
        f"code={A3_CODE} fz={A3_FZ}; bpas=cd00000). "
        f"Discovered {len(items)} IPS nds; fetched ok={ok} skip={skip} fail={fail}. "
        f"publication.pravo.gov.ru PDFs are image-only ABBYY scans (no text layer); "
        f"not OCR'd ({n_fz} FZ + {n_fkz} FKZ + {n_c} constitution/amend publication "
        f"rows remain catalog-only). Open data CSV is metadata (30/90/360 days), not "
        f"full text. Wayback/CC of official pravo.gov.ru URLs used only when live IPS "
        f"HTML fails. Not ConsultantPlus/Garant. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Official Internet Portal of Legal Information (pravo.gov.ru IPS + publication.pravo.gov.ru)",
        source_urls=source_urls, license_text=LICENSE,
        discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=cov, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    log.info("done ok=%s skip=%s fail=%s instruments=%s coverage=%s",
             ok, skip, fail, n_json, cov)


if __name__ == "__main__":
    main()
