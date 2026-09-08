#!/usr/bin/env python3
"""Israel: in-force national laws from official Knesset OData + Reshumot PDFs.

Official only. LawHome.aspx is behind Reblaze; this collector does not bypass WAF.
Full text: fs.knesset.gov.il PDFs from KNS_DocumentLaw. Not Nevo/Takdin.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "il"
COUNTRY = "Israel"
SOURCE_TYPE = "knesset_reshumot"
LICENSE = (
    "Research snapshot of official State of Israel / Knesset legislative publications. "
    "Reuse is governed by Knesset / State of Israel terms. Reshumot (רשומות) prevails. "
    "license: other. Not legal advice."
)
UA = DEFAULT_UA + " source=https://knesset.gov.il/OdataV4/ParliamentInfo/"
ODATA_V4 = "https://knesset.gov.il/OdataV4/ParliamentInfo"
ODATA_V2 = "https://knesset.gov.il/Odata/ParliamentInfo.svc"
WORKERS = 3
SLEEP = 0.45
log = logging.getLogger("il")
ART_HE = re.compile(r"(?im)^\s*((?:סעיף|פרק|סימן|תוספת)\s+[\d]+[א-ת]?)")
GROUP_PREF = {97: 0, 9: 1, 125: 2, 99: 3, 113: 4}


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )


def odata_get(url: str, params=None) -> dict:
    r = http_get(url, ua=UA, sleep=SLEEP, params=params, headers={"Accept": "application/json"}, retries=5)
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"HTTP {r.status_code} {url}")
    return r.json()


def dump_jsonl(path: Path, rows: list) -> None:
    atomic_write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def load_jsonl(path: Path) -> list:
    if not path.exists() or path.stat().st_size < 50:
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def odata_list_v4(entity: str) -> list:
    dest = ROOT / CC / "raw" / f"{entity}.jsonl"
    cached = load_jsonl(dest)
    url = f"{ODATA_V4}/{entity}"
    # nextLink from this host omits $skip; page with $skip instead.
    probe = odata_get(url, {"$top": 1, "$count": "true"})
    expected = int(probe.get("@odata.count") or 0)
    if cached and expected and len(cached) >= expected:
        log.info("resume %s %s", entity, len(cached))
        return cached
    if cached:
        log.info("refresh %s cached=%s expected=%s", entity, len(cached), expected)
    rows, seen, skip, pages = [], set(), 0, 0
    while pages < 500:
        data = odata_get(url, {"$top": 100, "$skip": skip, "$count": "true"})
        vals = data.get("value") or []
        if pages == 0:
            log.info("%s count=%s", entity, data.get("@odata.count"))
        if not vals:
            break
        for rec in vals:
            key = rec.get("Id")
            if key in seen:
                continue
            seen.add(key)
            rows.append(rec)
        skip += len(vals)
        pages += 1
        if pages % 5 == 0:
            log.info("%s pages=%s rows=%s", entity, pages, len(rows))
        if expected and len(rows) >= expected:
            break
        if len(vals) < 100:
            break
    dump_jsonl(dest, rows)
    return rows


def odata_list_v2(entity: str) -> list:
    dest = ROOT / CC / "raw" / f"{entity}.jsonl"
    cached = load_jsonl(dest)
    if cached:
        log.info("resume %s %s", entity, len(cached))
        return cached
    rows, seen, skip, pages = [], set(), 0, 0
    while pages < 500:
        data = odata_get(f"{ODATA_V2}/{entity}", {"$format": "json", "$top": 100, "$skip": skip, "$inlinecount": "allpages"})
        vals = data.get("value") or []
        if pages == 0:
            log.info("%s v2 count=%s", entity, data.get("odata.count"))
        if not vals:
            break
        for rec in vals:
            key = rec.get("DocumentLawID") or (rec.get("LawID"), rec.get("FilePath"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(rec)
        skip += len(vals)
        pages += 1
        if pages % 10 == 0:
            log.info("%s v2 pages=%s rows=%s", entity, pages, len(rows))
        if len(vals) < 100:
            break
    dump_jsonl(dest, rows)
    return rows


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


def split_he(text, law_id, source_url, date):
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_HE.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i+1].start() if i+1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9\u0590-\u05ff]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({"id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
                    "date_filed": date, "document_number": num, "source_url": source_url,
                    "record_type": "article", "article_number": num, "law_identifier": law_id,
                    "metadata": {"text_extraction": {"source": "official", "backend": "knesset-pdf"}}})
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def rank_doc(d):
    gt = d.get("GroupTypeID")
    path = (d.get("FilePath") or "").lower()
    app = (d.get("ApplicationDesc") or "").upper()
    is_pdf = 0 if (app == "PDF" or path.endswith(".pdf")) else 1
    return (GROUP_PREF.get(gt, 50), is_pdf, d.get("DocumentLawID") or "")


def fetch_pdf(url: str) -> bytes:
    r = http_get(url, ua=UA, sleep=SLEEP, retries=4, timeout=(20, 120),
                 headers={"Accept": "application/pdf,*/*", "Referer": "https://knesset.gov.il/"},
                 allow_empty=True)
    if r.status_code == 200 and r.content[:4] == b"%PDF":
        return r.content
    return b""


def status_of(rec):
    desc = rec.get("LawValidityDesc") or ""
    if desc == "תקף":
        return "current", True
    if "בוטל" in desc or "פקע" in desc:
        return "repealed", False
    return "unknown", None


def fetch_one(law, docs_by, names_by, bind_by, done):
    lid = law.get("Id")
    if lid is None:
        return "fail"
    rid = slug_id(CC, str(lid))
    if rid in done:
        return "skip"
    title = law.get("Name") or str(lid)
    date = iso_date((law.get("PublicationDate") or "")[:10])
    st, is_cur = status_of(law)
    cands = list(docs_by.get(lid, [])) + list(docs_by.get(str(lid), []))
    for nm in names_by.get(lid, []):
        alt = nm.get("LawID")
        if alt is not None:
            cands += docs_by.get(alt, []) + docs_by.get(str(alt), [])
    for b in bind_by.get(lid, []):
        alt = b.get("LawID")
        if alt is not None:
            cands += docs_by.get(alt, []) + docs_by.get(str(alt), [])
    uniq, seenp = [], set()
    for d in cands:
        p = d.get("FilePath") or d.get("DocumentLawID")
        if not p or p in seenp:
            continue
        seenp.add(p)
        uniq.append(d)
    picked = [d for d in sorted(uniq, key=rank_doc) if (d.get("FilePath") or "").lower().endswith(".pdf") or (d.get("ApplicationDesc") or "").upper() == "PDF"][:4]
    texts, used = [], None
    portal = "https://main.knesset.gov.il/Activity/Legislation/Laws/Pages/LawHome.aspx"
    for d in picked:
        path = d.get("FilePath") or ""
        raw = fetch_pdf(path)
        if not raw:
            continue
        t = pdf_to_text(raw)
        if len(t) < 80:
            continue
        texts.append(f"{d.get('GroupTypeDesc') or 'document'}\n\n{t}")
        used = path
        if d.get("GroupTypeID") == 97 and len(t) > 400:
            break
    text = "\n\n".join(texts).strip()
    if len(text) < 80:
        log_failure(CC, {"identifier": str(lid), "title": title, "source_url": used or portal,
                         "status": "failed", "reason": "empty_pdf_text", "n_cands": len(uniq)})
        return "fail"
    src = used or portal
    rec = base_record(
        cc=CC, country=COUNTRY, language="he", ident=str(lid), title=title, text=text,
        source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE, collector="il-knesset",
        date=date, official_identifier=str(lid),
        document_type="constitution" if law.get("IsBasicLaw") else "statute",
        law_status=st, is_current=is_cur, documents=split_he(text, rid, src, date),
        extra_meta={"discovery": {"method": "knesset_odata", "israel_law_id": lid},
                    "official_metadata": {k: law.get(k) for k in ("KnessetNum","IsBasicLaw","LawValidityDesc","LatestPublicationDate") if law.get(k) is not None},
                    "text_extraction": {"source": "official", "backend": "knesset-fs-pdf"}},
    )
    rec["canonical_law_url"] = portal
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    laws = odata_list_v4("KNS_IsraelLaw")
    names = odata_list_v4("KNS_IsraelLawName")
    binds = odata_list_v4("KNS_LawBinding")
    docs = odata_list_v2("KNS_DocumentLaw")
    docs_by, names_by, bind_by = defaultdict(list), defaultdict(list), defaultdict(list)
    for d in docs:
        lid = d.get("LawID")
        if lid is not None:
            docs_by[lid].append(d); docs_by[str(lid)].append(d)
    for n in names:
        i = n.get("IsraelLawID")
        if i is not None:
            names_by[i].append(n)
    for b in binds:
        i = b.get("IsraelLawID")
        if i is not None:
            bind_by[i].append(b)
    in_force = [x for x in laws if status_of(x)[0] == "current"]
    target = in_force or laws
    log.info("laws=%s in_force=%s docs=%s", len(laws), len(in_force), len(docs))
    done = existing_ids(CC)
    ok = skip = fail = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch_one, law, docs_by, names_by, bind_by, done) for law in target]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            if n % 40 == 0 or n == len(target):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(target), ok, skip, fail)
                write_summary(CC, country=COUNTRY, source="Knesset OData / Reshumot PDFs",
                              source_urls=["https://knesset.gov.il/OdataV4/ParliamentInfo/",
                                           "https://main.knesset.gov.il/Activity/Legislation/Laws/Pages/LawHome.aspx",
                                           "https://main.knesset.gov.il/Activity/Legislation/Laws/Pages/LawReshumot.aspx"],
                              license_text=LICENSE, discovered=len(target), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete",
                              notes="In-force KNS_IsraelLaw; text from official fs.knesset.gov.il PDFs", last_run=utcnow())
    notes = (
        "In-force national laws (KNS_IsraelLaw תקף) from official Knesset OData. "
        "Full text from fs.knesset.gov.il PDFs (KNS_DocumentLaw Reshumot / נוסח חדש). "
        "main.knesset.gov.il LawHome is Reblaze-blocked; no WAF bypass. Not Nevo/Takdin. "
        "Hebrew only; no machine translation. Reshumot prevails. "
        f"Catalog IsraelLaw={len(laws)} in_force={len(in_force)} DocumentLaw={len(docs)}."
    )
    write_summary(CC, country=COUNTRY, source="Knesset OData + Reshumot PDFs (fs.knesset.gov.il)",
                  source_urls=["https://knesset.gov.il/OdataV4/ParliamentInfo/",
                               "https://knesset.gov.il/Odata/ParliamentInfo.svc/",
                               "https://main.knesset.gov.il/Activity/Legislation/Laws/Pages/LawHome.aspx",
                               "https://main.knesset.gov.il/Activity/Legislation/Laws/Pages/LawReshumot.aspx"],
                  license_text=LICENSE, discovered=len(target), fetched=ok, skipped=skip, failed=fail,
                  coverage="in-force snapshot" if ok else "catalog-backed incomplete",
                  notes=notes, last_run=utcnow(), extra=f"started {t0}")
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
