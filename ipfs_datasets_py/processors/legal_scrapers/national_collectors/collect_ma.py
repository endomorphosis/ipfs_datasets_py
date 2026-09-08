#!/usr/bin/env python3
"""Morocco: Constitution + dahirs/lois from SGG Bulletin Officiel.

Official source only:
  https://www.sgg.gov.ma  (Secrétariat Général du Gouvernement)
  Constitution PDF: /Portals/1/lois/constitution_2011_Ar.pdf
  Individual texts: /Portals/1/lois/*.pdf  (dahirs, lois, décrets as published)
  Consolidated index: /arabe/textesconsolides.aspx
  Official Arabic/French as published on SGG.

Live TLS from this host often EOFs; on live failure / HTTP 429 of official
URLs, archive_fallbacks.py of those official URLs only.
Not Adala commercial (adala.ai / juritheque). Not used because SGG/BO
hosts the texts (live or Wayback of official sgg.gov.ma URLs).
No WAF bypass. No commercial DBs.
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
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "ma"
COUNTRY = "Morocco"
SOURCE_TYPE = "sgg_bo"
LICENSE = (
    "Official texts of the Kingdom of Morocco as published by the Secrétariat "
    "Général du Gouvernement (sgg.gov.ma) in the Bulletin Officiel "
    "(الجريدة الرسمية). The Bulletin Officiel prevails over this research "
    "snapshot. Not legal advice. Not Adala commercial compilations."
)
UA = DEFAULT_UA + " source=https://www.sgg.gov.ma/"
SGG = "https://www.sgg.gov.ma/"
CONST_AR = "http://www.sgg.gov.ma/Portals/1/lois/constitution_2011_Ar.pdf"
CONST_FR_BO = "http://www.sgg.gov.ma/BO/bulletin/FR/2011/BO_5964-Bis_Fr.pdf"
CONSOL = "http://www.sgg.gov.ma/arabe/textesconsolides.aspx"
WORKERS = 2
SLEEP = 0.5
log = logging.getLogger("ma")
ART_AR = re.compile(
    r"(?im)^\s*((?:المادة|مادة|الفصل|Article)\s+(?:[0-9\u0660-\u0669]+|[0-9]+(?:-[0-9]+)?|الأول(?:ى)?|الثاني(?:ة)?))"
)
PDF_NAME = re.compile(r"/Portals/1/lois/([^/?#]+\.pdf)", re.I)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
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
                check=False, capture_output=True, timeout=180,
            )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.decode("utf-8", "replace").strip()
    except Exception as exc:
        log.warning("pdftotext: %s", exc)
    return ""


def canon_sgg(url: str) -> str:
    if not url:
        return url
    u = url.replace("https://www.sgg.gov.ma", "http://www.sgg.gov.ma")
    u = u.replace("http://www.sgg.gov.ma:80", "http://www.sgg.gov.ma")
    u = u.split("#")[0]
    # drop DNN ver= cache busters but keep meaningful query-less PDF
    if ".pdf" in u.lower() and "?" in u:
        u = u.split("?", 1)[0]
    return u


def official_get(url: str, *, timestamp: Optional[str] = None, retries: int = 3) -> dict:
    url = canon_sgg(url)
    r = None
    try:
        r = http_get(url, ua=UA, sleep=SLEEP, retries=retries, timeout=(20, 90),
                     headers={"Accept": "application/pdf, text/html, */*"})
    except Exception as exc:
        log.info("live fail %s: %s — archive of official URL", url, exc)
        r = None
    if r is not None and r.status_code == 200 and r.content:
        body = r.content
        text = ""
        if body[:4] != b"%PDF":
            text = r.text or ""
            if af.is_challenge(text, r.status_code) or len(body) < 200:
                r = None
            else:
                return {"ok": True, "content": body, "text": text, "method": "live",
                        "final_url": r.url or url}
        else:
            return {"ok": True, "content": body, "text": "", "method": "live",
                    "final_url": r.url or url}
    if r is not None and r.status_code == 429:
        log.info("HTTP 429 %s — archive_fallbacks", url)
    # Prefer Wayback of the official URL (we have CDX timestamps). CC is slow
    # and rarely holds these PDFs.
    wb = af.get_wayback_content(url, timestamp=timestamp)
    if wb.get("status") == "success" and (wb.get("content") or wb.get("text")):
        return {
            "ok": True, "content": wb.get("content") or b"",
            "text": wb.get("text") or "",
            "method": "wayback",
            "final_url": wb.get("wayback_url") or url,
        }
    res = af.fetch_with_fallbacks(
        url, try_http=False, try_cc=False, try_archive_is=False, wayback_ts=timestamp,
    )
    if res.get("status") == "success" and (res.get("content") or res.get("text")):
        return {
            "ok": True, "content": res.get("content") or b"",
            "text": res.get("text") or "",
            "method": res.get("method") or "archive",
            "final_url": res.get("wayback_url") or url,
        }
    err = "archive_fail"
    if r is not None:
        err = f"http_{r.status_code}"
    return {"ok": False, "error": err}


def split_ar(text: str, law_id: str, source_url: str, date: Optional[str]) -> list[dict]:
    docs = split_articles(text, law_id, source_url, date)
    if len(docs) >= 2:
        return docs
    matches = list(ART_AR.finditer(text or ""))
    if len(matches) < 2:
        return []
    out, seen = [], set()
    for i, m in enumerate(matches):
        chunk = text[m.start(): (matches[i + 1].start() if i + 1 < len(matches) else len(text))].strip()
        if len(chunk) < 12:
            continue
        num = re.sub(r"\s+", " ", m.group(1)).strip()
        aid = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "-", num.lower()).strip("-")
        doc_id = f"{law_id}-{aid}"[:180]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({
            "id": doc_id, "title": chunk.split("\n", 1)[0][:200], "text": chunk,
            "date_filed": date, "document_number": num, "source_url": source_url,
            "record_type": "article", "article_number": num, "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "ma"}},
        })
        if len(out) >= 4000:
            break
    return out if len(out) >= 2 else []


def load_catalog() -> list[dict]:
    p = ROOT / CC / "raw" / "catalog.jsonl"
    if not p.exists() or p.stat().st_size < 50:
        return []
    items, seen = [], set()
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
    # reload properly
    items, seen = [], set()
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            key = (row.get("id") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            items.append(row)
    return items


def add_item(items, seen, row: dict):
    key = (row.get("id") or "").lower()
    if not key or key in seen:
        return
    seen.add(key)
    items.append(row)
    append_catalog(CC, row)


def pdf_id(url: str) -> str:
    m = PDF_NAME.search(url.replace("\\", "/"))
    if m:
        return unquote(m.group(1))
    name = Path(urlparse(url).path).name
    return unquote(name) or "unknown.pdf"


def classify(name: str, title: str = "") -> tuple[str, str]:
    n = (name or "") + " " + (title or "")
    nl = n.lower()
    if "constitution" in nl or "دستور" in n:
        return "constitution", "constitution"
    if re.search(r"\d+\.\d+\.\d+", name) or name.startswith("2."):
        return "decree", name
    return "statute", name


def discover() -> list[dict]:
    items = load_catalog()
    seen = {(x.get("id") or "").lower() for x in items}
    add_item(items, seen, {
        "id": "constitution_2011_Ar.pdf", "kind": "constitution", "lang": "ar",
        "url": CONST_AR, "title": "دستور المملكة المغربية 2011",
        "source": "known_constitution",
    })
    add_item(items, seen, {
        "id": "BO_5964-Bis_Fr.pdf", "kind": "constitution", "lang": "fr",
        "url": CONST_FR_BO, "title": "Constitution du Royaume du Maroc 2011 (BO 5964 bis FR)",
        "source": "known_constitution_fr",
    })
    if len(items) >= 80:
        log.info("resume catalog %s", len(items))
        return items
    prefixes = [
        "www.sgg.gov.ma/Portals/1/lois/",
        "sgg.gov.ma/Portals/1/lois/",
        "www.sgg.gov.ma/arabe/textesconsolides.aspx",
    ]
    for prefix in prefixes:
        recs = af.search_wayback_machine(
            prefix, match_type="prefix", limit=700,
            extra_filters=["mimetype:application/pdf"] if "/lois/" in prefix else None,
        )
        log.info("cdx %s n=%s", prefix, len(recs))
        for rec in recs:
            orig = canon_sgg(rec.get("original") or "")
            if not orig or "adala" in orig.lower():
                continue
            if "/Portals/1/lois/" in orig and orig.lower().endswith(".pdf"):
                name = pdf_id(orig)
                if name.lower() in {"thumbs.db"}:
                    continue
                kind, _ = classify(name)
                add_item(items, seen, {
                    "id": name, "kind": kind, "lang": "ar" if "_fr" not in name.lower() else "fr",
                    "url": orig, "wayback_ts": rec.get("timestamp"),
                    "title": name.replace(".pdf", "").replace("_", " "),
                    "source": "cdx_lois",
                })
    # textes consolides HTML for extra PDF links
    got = official_get(CONSOL)
    html = got.get("text") or ""
    for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I):
        from urllib.parse import urljoin
        orig = canon_sgg(urljoin("http://www.sgg.gov.ma/", href))
        if "/Portals/" not in orig and "/BO/" not in orig:
            continue
        name = pdf_id(orig)
        add_item(items, seen, {
            "id": name, "kind": classify(name)[0], "lang": "ar",
            "url": orig, "title": name, "source": "textesconsolides",
        })
    log.info("discovered %s", len(items))
    return items


def fetch_one(it: dict, done: set[str]) -> str:
    name = it.get("id") or "unknown"
    ident = name.replace(".pdf", "")
    if it.get("kind") == "constitution" and "constitution_2011_Ar" in name:
        ident = "constitution-2011-ar"
    elif it.get("kind") == "constitution":
        ident = f"constitution-2011-{it.get('lang') or 'fr'}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    url = canon_sgg(it.get("url") or "")
    got = official_get(url, timestamp=it.get("wayback_ts"))
    body = got.get("content") or b""
    text = ""
    backend = got.get("method") or "archive"
    used = got.get("final_url") or url
    if got.get("ok") and body[:4] == b"%PDF":
        text = pdf_to_text(body)
        backend = f"pdf-{(got.get('method') or 'archive')}"
    elif got.get("ok") and got.get("text"):
        text = html_to_text(got.get("text") or "")
        backend = f"html-{(got.get('method') or 'archive')}"
    if len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed",
                         "reason": got.get("error") or "empty_text"})
        return "fail"
    title = it.get("title") or ident
    # better title from first substantial line
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= 12 and not line.lower().startswith("%"):
            if any(k in line for k in ("دستور", "ظهير", "قانون", "مرسوم", "Constitution", "Dahir", "Loi")):
                title = line[:220]
                break
    lang = it.get("lang") or ("fr" if "_fr" in name.lower() or "/FR/" in url else "ar")
    date = "2011-07-29" if "constitution" in (it.get("kind") or "") else None
    ym = re.search(r"(19\d{2}|20\d{2})", name)
    if not date and ym:
        date = f"{ym.group(1)}-01-01"
    docs = split_ar(text, rid, used, date)
    rec = base_record(
        cc=CC, country=COUNTRY, language=lang, ident=ident, title=title,
        text=text, source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE,
        collector="collect_ma.py", date=date, official_identifier=ident,
        document_type=it.get("kind") or "statute",
        law_status="current", is_current=True, documents=docs,
        extra_meta={
            "discovery": {"method": it.get("source") or "sgg", "file": name,
                          "retrieval": got.get("method")},
            "retrieval": {"method": got.get("method") or "archive", "used_url": used,
                          "backend": backend},
            "text_extraction": {"source": "official", "backend": backend},
        },
    )
    rec["languages"] = [lang]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    items = sorted(items, key=lambda x: (
        0 if x.get("kind") == "constitution" else 1 if x.get("kind") == "statute" else 2,
        str(x.get("id") or ""),
    ))
    done = existing_ids(CC)
    ok = skip = fail = 0
    log.info("queue %s already=%s", len(items), len(done))
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
            ok += st == "ok"
            skip += st == "skip"
            fail += st == "fail"
            if n % 20 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(
                    CC, country=COUNTRY,
                    source="SGG Bulletin Officiel (sgg.gov.ma)",
                    source_urls=[SGG, CONST_AR, CONSOL],
                    license_text=LICENSE, discovered=len(items), fetched=ok,
                    skipped=skip, failed=fail, coverage="catalog-backed incomplete",
                    notes="Constitution + dahirs/lois PDFs from official SGG. Not Adala commercial.",
                    last_run=utcnow(),
                )
    coverage = "snapshot" if ok else "empty"
    if items and fail == 0 and ok + skip >= len(items):
        coverage = "national-laws snapshot"
    notes = (
        "Constitution 2011 (Arabic official PDF; French BO 5964 bis) plus "
        "individual dahirs/lois PDFs from sgg.gov.ma/Portals/1/lois. "
        "Live TLS often fails from this host; texts via live when possible "
        "else Wayback/Common Crawl of official SGG URLs. Weekly historic BO "
        "issues (1913–) not ingested as whole books — national statute PDFs "
        "first. Not Adala commercial. "
        f"429 uses archive_fallbacks of official URLs. Started {t0}."
    )
    write_summary(
        CC, country=COUNTRY,
        source="Secrétariat Général du Gouvernement / Bulletin Officiel (sgg.gov.ma)",
        source_urls=[SGG, CONST_AR, CONST_FR_BO, CONSOL],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage=coverage, notes=notes, last_run=utcnow(), extra=f"started {t0}",
    )
    (ROOT / CC / "logs" / "DONE").write_text(json.dumps({
        "ok": ok, "skip": skip, "fail": fail, "discovered": len(items), "coverage": coverage,
    }, indent=2) + "\n", encoding="utf-8")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", ok, skip, fail, coverage)


if __name__ == "__main__":
    main()
