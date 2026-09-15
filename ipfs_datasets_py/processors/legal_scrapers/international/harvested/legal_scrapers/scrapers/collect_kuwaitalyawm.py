#!/usr/bin/env python3
"""Kuwait: official gazette القوانين (الكويت اليوم) + e.gov.kw texts.

Category 9 listing is official JSON on kuwaitalyawm.media.gov.kw.
Flip-book full pages are subscriber-only; this collector does not bypass
that paywall. Full texts: e.gov.kw official PDFs (live or Wayback of those
official URLs) and Wayback snapshots of official kuwaitalyawm/e.gov.kw pages.
No commercial Gulf law databases.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests
import urllib3
from requests.adapters import HTTPAdapter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
from archive_fallbacks import get_wayback_content, search_wayback_machine

urllib3.disable_warnings()

CC = "kw"
COUNTRY = "Kuwait"
SOURCE_TYPE = "kuwaitalyawm"
LICENSE = (
    "Research snapshot of official Kuwait gazette (الكويت اليوم / Ministry of Information) "
    "and e.gov.kw official publications. Reuse is governed by Ministry of Information / "
    "official gazette terms. license: other. Not legal advice."
)
UA = DEFAULT_UA + " source=https://kuwaitalyawm.media.gov.kw/"
BASE = "https://kuwaitalyawm.media.gov.kw"
JSON_URL = BASE + "/online/AdsCategoryJson"
WORKERS = 8
SLEEP = 0.25
log = logging.getLogger("kw")
ART_AR = re.compile(r"(?im)^\s*((?:المادة|مادة)\s+(?:[0-9\u0660-\u0669]+|الأولى|الثانية|الثالثة))")

EGOV_PDFS = [
    "https://www.e.gov.kw/sites/kgoArabic/Forms/DastoorKuwaity.pdf",
    "https://e.gov.kw/sites/kgoEnglish/Forms/DastoorKuwaity.pdf",
    "https://www.e.gov.kw/sites/kgoArabic/Forms/DastoorKuwaity.pdf",
]


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )


def kw_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json, text/html, application/pdf, */*"})
    ad = HTTPAdapter(pool_connections=6, pool_maxsize=6, max_retries=0)
    s.mount("https://", ad)
    s.mount("http://", ad)
    return s


def kw_get(url, *, data=None, timeout=(20, 90), headers=None):
    time.sleep(SLEEP)
    s = kw_session()
    hdrs = headers or {}
    last = None
    for verify in (True, False):
        try:
            if data is None:
                r = s.get(url, timeout=timeout, headers=hdrs, verify=verify, allow_redirects=True)
            else:
                r = s.post(url, data=data, timeout=timeout, headers=hdrs, verify=verify, allow_redirects=True)
            last = r
            if r.status_code == 200 and r.content:
                return r
            if r.status_code in (403, 404):
                return r
        except requests.RequestException as exc:
            last = exc
            continue
    if isinstance(last, requests.Response):
        return last
    raise RuntimeError(f"GET failed {url}: {last}")


# import time after function uses it - need import
import time  # noqa: E402


def pdf_to_text(raw: bytes) -> str:
    if not raw or raw[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(raw); tmp.flush()
            proc = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                                  check=False, capture_output=True, timeout=180)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext: %s", exc)
    return ""


def split_ar(text, law_id, source_url, date):
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_AR.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i+1].start() if i+1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({"id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
                    "date_filed": date, "document_number": num, "source_url": source_url,
                    "record_type": "article", "article_number": num, "law_identifier": law_id,
                    "metadata": {"text_extraction": {"source": "official", "backend": "kw"}}})
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def dt_payload(start: int, length: int = 100) -> dict:
    data = {
        "draw": 1, "start": start, "length": length, "ID": "9",
        "AdsTitle": "", "EditionNo": "", "startdate": "", "enddate": "",
        "search[value]": "", "search[regex]": "false",
        "order[0][column]": 1, "order[0][dir]": "desc",
    }
    cols = ["AdsTitle", "ID", "EditionNo", "EditionType", "EditionDate", "HijriDate"]
    for i, c in enumerate(cols):
        data[f"columns[{i}][data]"] = c
        data[f"columns[{i}][name]"] = c
        data[f"columns[{i}][searchable]"] = "true"
        data[f"columns[{i}][orderable]"] = "true"
        data[f"columns[{i}][search][value]"] = ""
        data[f"columns[{i}][search][regex]"] = "false"
    return data


def discover_category() -> list[dict]:
    dest = ROOT / CC / "raw" / "category9.jsonl"
    if dest.exists() and dest.stat().st_size > 100:
        rows = []
        with dest.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        if rows:
            log.info("resume category9 %s", len(rows))
            return rows
    rows, start, total = [], 0, None
    while start < 5000:
        r = kw_get(JSON_URL, data=dt_payload(start, 100),
                   headers={"X-Requested-With": "XMLHttpRequest",
                            "Referer": BASE + "/online/AdsCategory/9",
                            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
        if r.status_code != 200:
            log.warning("category json HTTP %s", r.status_code)
            break
        data = r.json()
        if total is None:
            total = int(data.get("recordsTotal") or 0)
            log.info("category9 recordsTotal=%s", total)
        batch = data.get("data") or []
        if not batch:
            break
        rows.extend(batch)
        start += len(batch)
        log.info("category9 start=%s n=%s", start, len(rows))
        if total and len(rows) >= total:
            break
        if len(batch) < 100:
            break
    atomic_write(dest, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))
    return rows


def write_law(ident, title, text, source_url, date, extra_meta, doc_type="statute"):
    rid = slug_id(CC, ident)
    if rid in existing_ids(CC):
        return "skip"
    if len(text or "") < 80:
        return "fail"
    rec = base_record(
        cc=CC, country=COUNTRY, language="ar", ident=ident, title=title, text=text,
        source_url=source_url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="kw-kuwaitalyawm", date=date, official_identifier=ident,
        document_type=doc_type, law_status="current", is_current=True,
        documents=split_ar(text, rid, source_url, date), extra_meta=extra_meta,
    )
    write_instrument(CC, rec)
    return "ok"


def add_egov_pdfs() -> tuple[int, int]:
    ok = fail = 0
    urls = list(EGOV_PDFS)
    extra = search_wayback_machine(
        "https://www.e.gov.kw/sites/kgoArabic/Forms/", match_type="prefix",
        limit=80, extra_filters=["mimetype:application/pdf"],
    )
    extra += search_wayback_machine(
        "https://e.gov.kw/sites/kgoEnglish/Forms/", match_type="prefix",
        limit=80, extra_filters=["mimetype:application/pdf"],
    )
    log.info("egov wayback pdf cdx=%s", len(extra))
    seen = set()
    jobs = []
    for u in urls:
        jobs.append({"original": u, "timestamp": None, "source": "live-or-wayback"})
    for rec in extra:
        orig = rec.get("original") or ""
        if not orig.lower().endswith(".pdf"):
            continue
        if orig in seen:
            continue
        seen.add(orig)
        jobs.append({"original": orig, "timestamp": rec.get("timestamp"), "source": "wayback"})
    for job in jobs:
        orig = job["original"]
        ident = Path(orig.split("?")[0]).stem[:80] or "egov-pdf"
        text = ""
        src = orig
        # live
        try:
            r = kw_get(orig, headers={"Accept": "application/pdf,*/*"})
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                text = pdf_to_text(r.content)
        except Exception as exc:
            log.info("live pdf fail %s: %s", orig, exc)
        if len(text) < 80:
            res = get_wayback_content(orig, timestamp=job.get("timestamp"))
            if res.get("status") == "success" and (res.get("content") or b"")[:4] == b"%PDF":
                text = pdf_to_text(res["content"])
                src = res.get("wayback_url") or orig
            elif res.get("status") == "success" and res.get("text"):
                text = html_to_text(res["text"])
                src = res.get("wayback_url") or orig
        title = ident.replace("_", " ")
        if "dastoor" in ident.lower() or "dastor" in ident.lower():
            title = "الدستور الكويتي والمذكرة التفسيرية"
            doc_type = "constitution"
        else:
            doc_type = "statute"
        st = write_law(ident, title, text, orig, None, {
            "discovery": {"method": job["source"], "official_host": "e.gov.kw"},
            "archive": {"retrieved_url": src},
            "text_extraction": {"source": "official", "backend": "egov-pdf"},
        }, doc_type=doc_type)
        if st == "ok":
            ok += 1
            log.info("egov pdf ok %s chars=%s", ident, len(text))
        elif st == "fail":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": orig, "status": "failed", "reason": "empty_pdf"})
    return ok, fail


def add_wayback_gazette_html() -> tuple[int, int]:
    recs = search_wayback_machine(
        "http://kuwaitalyawm.media.gov.kw/", match_type="prefix", limit=400,
        extra_filters=["mimetype:text/html"],
    )
    log.info("kw wayback html cdx=%s", len(recs))
    ok = fail = 0
    # keep likely law/issue pages
    keep = []
    for rec in recs:
        orig = rec.get("original") or ""
        if re.search(r"ملحق|اعداد|AdsCategory|law|qanun|قانون", orig, re.I):
            try:
                ln = int(rec.get("length") or 0)
            except Exception:
                ln = 0
            if ln >= 8000:
                keep.append(rec)
    seen = set()
    for rec in keep[:80]:
        orig = rec.get("original")
        if orig in seen:
            continue
        seen.add(orig)
        res = get_wayback_content(orig, timestamp=rec.get("timestamp"))
        html = res.get("text") or ""
        text = html_to_text(html)
        if len(text) < 200:
            fail += 1
            continue
        ident = re.sub(r"[^a-zA-Z0-9\u0600-\u06ff]+", "-", orig)[:80]
        title = orig
        m = re.search(r"<title>\s*([^<]+)", html, re.I)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip() or orig
        st = write_law("wb-" + ident, title, text, orig, None, {
            "discovery": {"method": "wayback_official_gazette"},
            "archive": {"wayback_url": res.get("wayback_url"), "timestamp": rec.get("timestamp")},
            "text_extraction": {"source": "archive-of-official", "backend": "wayback"},
        })
        if st == "ok":
            ok += 1
        elif st == "fail":
            fail += 1
    return ok, fail


def main():
    setup()
    t0 = utcnow()
    cat = discover_category()
    log.info("category9 listed %s (flip viewer is subscriber-only; texts from e.gov.kw / wayback)", len(cat))
    atomic_write(ROOT / CC / "raw" / "category9_meta.json", json.dumps({
        "records": len(cat), "note": "gazette flip is subscriber-only",
    }, ensure_ascii=False, indent=2))
    ok = skip = fail = 0
    eok, efail = add_egov_pdfs()
    wok, wfail = add_wayback_gazette_html()
    ok += eok + wok
    fail += efail + wfail
    notes = (
        f"Official gazette category القوانين (AdsCategory/9) lists {len(cat)} instruments via "
        "AdsCategoryJson. The flip-book full-text viewer is subscriber-only "
        "('خدمة تصفح الإصدار متاحة فقط للمشتركين'); this collector did not bypass that. "
        "Full texts harvested from official e.gov.kw PDFs (live or Wayback of those URLs) "
        "and Wayback snapshots of official kuwaitalyawm HTML. e.gov.kw live often 403 "
        "(Azure gateway). Not commercial Gulf DBs. Arabic."
    )
    write_summary(CC, country=COUNTRY, source="الكويت اليوم (Ministry of Information) + e.gov.kw",
                  source_urls=["https://kuwaitalyawm.media.gov.kw/",
                               "https://kuwaitalyawm.media.gov.kw/online/AdsCategory/9",
                               "https://www.e.gov.kw/sites/kgoarabic/Pages/ApplicationPages/Policies.aspx"],
                  license_text=LICENSE, discovered=len(cat), fetched=ok, skipped=skip, failed=fail,
                  coverage="partial-official-fulltext", notes=notes, last_run=utcnow(), extra=f"started {t0}")
    log.info("done ok=%s fail=%s listed=%s", ok, fail, len(cat))


if __name__ == "__main__":
    main()
