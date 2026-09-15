#!/usr/bin/env python3
"""Kyrgyzstan: Constitution + codes + in-force laws from ЦБД / cbd.minjust.gov.kg API.

Official only (Ministry of Justice Centralized Bank of Legal Information).
  POST /api/v1/GetDocuments?pageNumber=&pageSize=  body {refTypeId, refStatusId}
  GET  /api/v1/GetMajorDocuments
  GET  /api/v1/GetEdition?editionId=&lang=ru|kg  → contentRu HTML
  GET  /api/v1/GetFile?refId=&lang=ru             → DOCX fallback (optional)

First batch: major docs + all in-force codes + in-force constitution + capped in-force laws.
Do not scrape all ~209k NPAs in one run. No captcha solve / WAF bypass. ≤1 req/s.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "kg"
COUNTRY = "Kyrgyzstan"
SOURCE_TYPE = "cbd_minjust_gov_kg"
LICENSE = (
    "Official texts of the Kyrgyz Republic as published in the Centralized Bank of "
    "Legal Information (ЦБД / УМББ), Ministry of Justice — cbd.minjust.gov.kg. "
    "The authentic official publication prevails over this research snapshot. "
    "Not legal advice."
)
UA = DEFAULT_UA + " source=https://cbd.minjust.gov.kg/"
API = "https://cbd.minjust.gov.kg/api/v1"
PORTAL = "https://cbd.minjust.gov.kg"
SLEEP = float(os.environ.get("KG_SLEEP", "1.0"))
PAGE_SIZE = int(os.environ.get("KG_PAGE_SIZE", "50"))
MAX_LAWS = int(os.environ.get("KG_MAX_LAWS", "300"))
LANG = os.environ.get("KG_LANG", "ru")
log = logging.getLogger("kg")

# classificatorId=5 act types; classificatorId=22 statuses
REF_CONSTITUTION = "0010"
REF_LAW = "0020"
REF_CODE = "0030"
STATUS_IN_FORCE = "10"

ART_RE = re.compile(
    r"(?im)^\s*((?:Статья|Статьясы|Берене|Article)\s+[0-9IVXLCDM]+[A-Za-zА-Яа-яёӘәӨөҮүҢң]?)(?:\.|\b)"
)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def session():
    return get_session(UA)


def polite_sleep():
    if SLEEP:
        time.sleep(SLEEP)


def api_get(path: str, params: Optional[dict] = None, timeout=(20, 120)) -> dict:
    url = path if path.startswith("http") else f"{API}/{path.lstrip('/')}"
    last = None
    for attempt in range(1, 5):
        polite_sleep()
        try:
            r = session().get(url, params=params, timeout=timeout,
                              headers={"Accept": "application/json, */*", "Referer": PORTAL + "/"})
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(min(30, 2 ** attempt))
                last = r
                continue
            if r.status_code == 200 and r.content:
                ctype = (r.headers.get("content-type") or "").lower()
                if "json" in ctype or r.content[:1] in (b"{", b"["):
                    try:
                        return {"status": "success", "json": r.json(), "content": r.content,
                                "content_type": ctype, "retrieval": "live", "http_status": 200,
                                "final_url": r.url}
                    except Exception:
                        pass
                return {"status": "success", "content": r.content, "text": "",
                        "content_type": ctype, "retrieval": "live", "http_status": 200,
                        "final_url": r.url}
            if r.status_code in (404, 410, 403, 401):
                return {"status": "error", "error": f"http_{r.status_code}", "http_status": r.status_code}
            last = r
        except Exception as exc:
            last = exc
            time.sleep(min(20, 1.5 * attempt))
    return {"status": "error", "error": repr(last)}


def api_post(path: str, body: dict, params: Optional[dict] = None, timeout=(20, 120)) -> dict:
    url = path if path.startswith("http") else f"{API}/{path.lstrip('/')}"
    last = None
    for attempt in range(1, 5):
        polite_sleep()
        try:
            r = session().post(
                url, params=params, json=body, timeout=timeout,
                headers={
                    "Accept": "application/json, */*",
                    "Content-Type": "application/json",
                    "Origin": PORTAL,
                    "Referer": PORTAL + "/",
                },
            )
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(min(30, 2 ** attempt))
                last = r
                continue
            if r.status_code == 200 and r.content:
                try:
                    return {"status": "success", "json": r.json(), "retrieval": "live",
                            "http_status": 200, "final_url": r.url}
                except Exception as exc:
                    return {"status": "error", "error": f"json:{exc}", "http_status": 200}
            last = r
        except Exception as exc:
            last = exc
            time.sleep(min(20, 1.5 * attempt))
    return {"status": "error", "error": repr(last)}


def canonical_url(doc_code: str, lang: str = "ru-ru") -> str:
    return f"{PORTAL}/act/view/{lang}/{doc_code}"


def catalog_path() -> Path:
    return ROOT / CC / "raw" / "catalog.jsonl"


def load_catalog() -> list[dict]:
    p = catalog_path()
    if not p.exists() or p.stat().st_size < 40:
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
    atomic_write(catalog_path(), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))


def row_from_listing(rec: dict, form: str, doc_type: str) -> Optional[dict]:
    code = str(rec.get("documentCode") or "").strip()
    if not code:
        return None
    edition = rec.get("lastEdition")
    title = (rec.get("nameRu") or rec.get("nameKg") or code).strip()
    title = re.sub(r"\s+", " ", title)
    status = rec.get("status")
    if isinstance(status, dict):
        status_name = status.get("nameRus") or status.get("nameKyr") or ""
        status_code = status.get("code") or ""
    else:
        status_name = str(status or "")
        status_code = ""
    date = iso_date((rec.get("dateAdopted") or "")[:10]) or iso_date((rec.get("datePublication") or "")[:10])
    return {
        "doc_id": code,
        "document_code": code,
        "edition_id": edition,
        "url": canonical_url(code),
        "title": title,
        "form": form,
        "document_type": doc_type,
        "status": status_name,
        "status_code": status_code,
        "date": date,
        "vid": rec.get("vid") or "",
    }


def fetch_facet(ref_type: str, form: str, doc_type: str, *, max_items: Optional[int] = None) -> list[dict]:
    out: list[dict] = []
    page = 1
    empty = 0
    while page <= 200:
        body = {"refTypeId": ref_type, "refStatusId": STATUS_IN_FORCE, "lang": LANG}
        res = api_post("GetDocuments", body, params={"pageNumber": page, "pageSize": PAGE_SIZE})
        if res.get("status") != "success":
            log.warning("GetDocuments %s page=%s fail %s", ref_type, page, res.get("error"))
            empty += 1
            if empty >= 2:
                break
            page += 1
            continue
        data = res["json"]
        rows = data.get("data") or []
        filtered = data.get("filteredResultsCount") or data.get("recordsFiltered")
        added = 0
        for rec in rows:
            row = row_from_listing(rec, form, doc_type)
            if not row:
                continue
            out.append(row)
            added += 1
            if max_items and len(out) >= max_items:
                log.info("facet %s capped at %s (filtered=%s)", form, len(out), filtered)
                return out
        log.info("facet %s page=%s rows=%s added=%s total=%s filtered=%s",
                 form, page, len(rows), added, len(out), filtered)
        if not rows:
            empty += 1
            if empty >= 2:
                break
        else:
            empty = 0
        if filtered is not None and len(out) >= int(filtered):
            break
        if len(rows) < PAGE_SIZE:
            break
        page += 1
    return out


def fetch_major() -> list[dict]:
    res = api_get("GetMajorDocuments")
    out = []
    if res.get("status") != "success":
        log.warning("GetMajorDocuments fail %s", res.get("error"))
        return out
    for rec in res.get("json") or []:
        status = rec.get("status") or {}
        code = str(rec.get("documentCode") or "").strip()
        if not code:
            continue
        name = (rec.get("nameRu") or rec.get("nameKg") or code).strip()
        st_code = status.get("code") if isinstance(status, dict) else ""
        # Prefer in-force; keep constitution even if status odd
        is_const = "конституция" in name.lower() or code in ("1-2", "1-1")
        doc_type = "constitution" if is_const else "statute"
        form = "constitution" if is_const else "major"
        if st_code and st_code != STATUS_IN_FORCE and not is_const:
            continue
        out.append({
            "doc_id": code,
            "document_code": code,
            "edition_id": rec.get("lastEdition"),
            "url": canonical_url(code),
            "title": re.sub(r"\s+", " ", name),
            "form": form,
            "document_type": doc_type,
            "status": (status.get("nameRus") if isinstance(status, dict) else "") or "",
            "status_code": st_code or "",
            "date": None,
            "vid": "",
        })
    log.info("GetMajorDocuments n=%s", len(out))
    return out


def discover() -> list[dict]:
    existing = load_catalog()
    if existing and len(existing) >= 30 and os.environ.get("KG_REDISCOVER") != "1":
        norm = []
        for it in existing:
            code = it.get("document_code") or it.get("doc_id")
            if not code:
                continue
            row = dict(it)
            row["document_code"] = str(code)
            row["doc_id"] = str(it.get("doc_id") or code)
            if not row.get("edition_id") and row.get("last_edition"):
                row["edition_id"] = row["last_edition"]
            if not row.get("date") and row.get("date_adopted"):
                row["date"] = iso_date(str(row["date_adopted"])[:10])
            if not row.get("url"):
                row["url"] = canonical_url(row["document_code"])
            if not row.get("form"):
                row["form"] = row.get("ref_type") or "law"
            if not row.get("title"):
                row["title"] = row.get("title_kg") or row["document_code"]
            norm.append(row)
        log.info("resume catalog n=%s", len(norm))
        return norm
    best: dict[str, dict] = {}

    def add_all(rows: list[dict]):
        for row in rows:
            did = row["doc_id"]
            prev = best.get(did)
            if not prev:
                best[did] = row
            else:
                # Prefer richer edition / constitution typing
                if row.get("document_type") == "constitution":
                    prev["document_type"] = "constitution"
                    prev["form"] = "constitution"
                if row.get("edition_id") and not prev.get("edition_id"):
                    prev["edition_id"] = row["edition_id"]
                if row.get("title") and len(row["title"]) > len(prev.get("title") or ""):
                    prev["title"] = row["title"]

    add_all(fetch_major())
    add_all(fetch_facet(REF_CONSTITUTION, "constitution", "constitution"))
    add_all(fetch_facet(REF_CODE, "code", "statute"))
    add_all(fetch_facet(REF_LAW, "law", "statute", max_items=MAX_LAWS))

    items = list(best.values())
    items.sort(key=lambda x: (
        0 if x.get("document_type") == "constitution" else 1,
        0 if x.get("form") == "code" else 1,
        0 if x.get("form") == "major" else 1,
        x["doc_id"],
    ))
    save_catalog(items)
    log.info("catalog n=%s (max_laws=%s)", len(items), MAX_LAWS)
    return items


def ensure_edition(it: dict) -> Optional[int]:
    ed = it.get("edition_id")
    if ed:
        try:
            return int(ed)
        except Exception:
            pass
    # Resolve via GetDocument
    code = it["document_code"]
    res = api_get("GetDocument", params={"DocumentCode": code})
    if res.get("status") != "success":
        return None
    meta = res.get("json") or {}
    # lastEdition may be nested
    ed = meta.get("lastEdition") or meta.get("editionId")
    if isinstance(ed, dict):
        ed = ed.get("id") or ed.get("editionId")
    if ed is None:
        # editions list?
        editions = meta.get("editions") or meta.get("editionHistory") or []
        if editions and isinstance(editions, list):
            ed = editions[0].get("id") if isinstance(editions[0], dict) else editions[0]
    # Some payloads expose last edition under different keys — scan
    if ed is None:
        for k, v in meta.items():
            if "edition" in k.lower() and isinstance(v, int):
                ed = v
                break
    if ed is not None:
        it["edition_id"] = ed
        if meta.get("nameRus"):
            it["title"] = re.sub(r"\s+", " ", meta["nameRus"]).strip()
        if meta.get("dateAdopted"):
            it["date"] = iso_date(str(meta["dateAdopted"])[:10]) or it.get("date")
        ref = meta.get("refTypeId") or {}
        if isinstance(ref, dict) and "конституция" in (ref.get("nameRus") or "").lower():
            it["document_type"] = "constitution"
            it["form"] = "constitution"
    try:
        return int(ed) if ed is not None else None
    except Exception:
        return None


def extract_html_body(html: str) -> str:
    if not html:
        return ""
    text = html_to_text(html)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def split_kg(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_RE.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9а-яёәөүң]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
            "date_filed": date, "document_number": num, "source_url": source_url,
            "record_type": "article", "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "cbd-html"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def fetch_edition_text(edition_id: int) -> tuple[str, str, dict]:
    """Return (text, backend, raw_res_meta)."""
    res = api_get("GetEdition", params={"editionId": edition_id, "lang": LANG})
    if res.get("status") == "success" and isinstance(res.get("json"), dict):
        js = res["json"]
        html = js.get("contentRu") if LANG == "ru" else (js.get("contentKg") or js.get("contentRu"))
        if not html:
            html = js.get("contentRu") or js.get("contentKg") or ""
        text = extract_html_body(html) if isinstance(html, str) else ""
        if len(text) >= 120:
            return text, "GetEdition-html", {"edition_name": js.get("nameRus") or js.get("nameKyr")}
    # DOCX fallback via GetFile
    res2 = api_get("GetFile", params={"refId": edition_id, "lang": LANG})
    if res2.get("status") == "success" and res2.get("content"):
        raw = res2["content"]
        # try python-docx if available; else store note
        try:
            import io
            import zipfile
            # minimal docx XML text extract
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                xml = zf.read("word/document.xml").decode("utf-8", "replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            xml = re.sub(r"<[^>]+>", "", xml)
            text = re.sub(r"\n{3,}", "\n\n", html.unescape(xml)).strip() if False else re.sub(r"\n{3,}", "\n\n", __import__("html").unescape(xml)).strip()
            if len(text) >= 120:
                return text, "GetFile-docx", {}
        except Exception as exc:
            log.info("docx extract fail edition=%s: %s", edition_id, exc)
    return "", "empty", {}


def normalize_item(it: dict) -> dict:
    """Accept both our schema and sibling-agent catalog rows."""
    out = dict(it)
    code = out.get("document_code") or out.get("doc_id") or ""
    out["document_code"] = str(code).strip()
    out["doc_id"] = out.get("doc_id") or out["document_code"]
    if not out.get("edition_id") and out.get("last_edition"):
        out["edition_id"] = out["last_edition"]
    if not out.get("date") and out.get("date_adopted"):
        out["date"] = iso_date(str(out["date_adopted"])[:10])
    if not out.get("url") and out["document_code"]:
        out["url"] = canonical_url(out["document_code"])
    if not out.get("title"):
        out["title"] = out.get("title_kg") or out["document_code"]
    if not out.get("form"):
        out["form"] = out.get("ref_type") or "law"
    return out


def fetch_one(it: dict, done: set[str]) -> str:
    it = normalize_item(it)
    code = it["document_code"]
    ident = code
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    edition_id = ensure_edition(it)
    if not edition_id:
        log_failure(CC, {"id": rid, "url": it["url"], "status": "failed", "reason": "no_edition"})
        return "fail"
    text, backend, extra = fetch_edition_text(edition_id)
    if len(text) < 120:
        # archive fallback of official act URL only
        af_res = af.fetch_with_fallbacks(it["url"], try_http=False)
        html = af_res.get("text") or ""
        if af_res.get("status") == "success" and len(html) > 200:
            text = extract_html_body(html) or html_to_text(html)
            backend = f"archive:{af_res.get('method') or 'wayback'}"
        if len(text) < 120:
            log_failure(CC, {"id": rid, "url": it["url"], "status": "failed",
                             "reason": "empty_text", "edition_id": edition_id})
            return "fail"
    title = it.get("title") or code
    date = it.get("date")
    is_const = it.get("document_type") == "constitution" or "конституция" in title.lower()
    repealed = bool(re.search(r"(?i)утратил[ао]?\s+силу|прекратил[ао]?\s+действие|күчүн жогот", title + " " + (it.get("status") or "")))
    docs = split_kg(text, rid, it["url"], date)
    rec = base_record(
        cc=CC, country=COUNTRY, language="ru", ident=ident, title=title,
        text=text, source_url=it["url"], source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_kg.py", date=date, official_identifier=code,
        document_type="constitution" if is_const else "statute",
        law_status="repealed" if repealed else "current",
        is_current=False if repealed else True, documents=docs,
        extra_meta={
            "discovery": {
                "method": "cbd_getdocuments_facet",
                "form": it.get("form"),
                "document_code": code,
                "edition_id": edition_id,
                "vid": it.get("vid"),
            },
            "text_extraction": {"source": "official", "backend": backend},
            "retrieval": {"method": "live", "api": "cbd.minjust.gov.kg"},
            "kyrgyz_url": canonical_url(code, "ky-kg"),
            "edition_meta": extra,
        },
        extra_fields={"canonical_document_url": it["url"], "information_url": it["url"]},
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def write_progress(items, counters, coverage, extra=""):
    notes = (
        "ЦБД minjust.gov.kg API: GetMajorDocuments + GetDocuments "
        f"(refTypeId constitution/code/law, refStatusId=10 in-force; laws capped at {MAX_LAWS}). "
        "Bodies from GetEdition contentRu HTML; GetFile DOCX fallback. "
        "Canonical source_url act/view/ru-ru/{DocumentCode}. "
        "Not a full 209k NPA dump. Russian as published; Kyrgyz URL recorded. "
        + extra
    )
    write_summary(
        CC, country=COUNTRY,
        source="ЦБД / Ministry of Justice of Kyrgyzstan (cbd.minjust.gov.kg)",
        source_urls=[
            PORTAL + "/",
            API + "/GetDocuments",
            API + "/GetMajorDocuments",
            API + "/GetEdition",
            canonical_url("1-2"),
        ],
        license_text=LICENSE, discovered=len(items), fetched=counters["ok"],
        skipped=counters["skip"], failed=counters["fail"], coverage=coverage, notes=notes,
    )


def main():
    setup()
    t0 = utcnow()
    items = discover()
    counters = {"ok": 0, "skip": 0, "fail": 0}
    done = existing_ids(CC)
    log.info("queue n=%s already=%s sleep=%s", len(items), len(done), SLEEP)
    for n, it in enumerate(items, 1):
        try:
            st = fetch_one(it, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"url": it.get("url"), "status": "failed", "reason": repr(exc)})
            log.exception("fetch fail %s", it.get("doc_id"))
        counters[st] = counters.get(st, 0) + 1
        if n % 10 == 0 or n == len(items):
            log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items),
                     counters["ok"], counters["skip"], counters["fail"])
            write_progress(items, counters, "catalog-backed incomplete")
    cov = "snapshot-in-force-primary"
    if counters["ok"] + counters["skip"] >= 20:
        cov = "in-force-constitution-codes-laws-batch"
    write_progress(items, counters, cov, extra=f"Started {t0}.")
    atomic_write(ROOT / CC / "raw" / "stats.json", json.dumps({
        "discovered": len(items), "ok": counters["ok"], "skip": counters["skip"],
        "failed": counters["fail"], "coverage": cov, "started": t0, "finished": utcnow(),
        "max_laws": MAX_LAWS,
    }, indent=2) + "\n")
    log.info("done %s coverage=%s", counters, cov)


if __name__ == "__main__":
    main()
