#!/usr/bin/env python3
"""United Kingdom: legislation.gov.uk (The National Archives) CLML API.

Official sources only:
  - https://www.legislation.gov.uk/developer
  - Atom lists: /ukpga/data.feed  (then /uksi/data.feed if feasible)
  - Document CLML: /ukpga/{year}/{number}/data.xml  (latest / in-force revised)

UK Public General Acts in force first, then UK Statutory Instruments if feasible.
Does not use BAILII, Westlaw, or other unofficial/commercial databases.
Honor robots.txt (Disallow */data.pdf and */data.docx; sitemaps and data.xml allowed).
Fair use: 3000 API requests / 5 minutes. No WAF bypass.
Open Government Licence v3.0.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import archive_fallbacks as af

CC = "uk"
COUNTRY = "United Kingdom"
SOURCE_TYPE = "legislation_gov_uk"
LICENSE = (
    "Open Government Licence v3.0 (The National Archives / legislation.gov.uk). "
    "All content is available under the Open Government Licence v3.0 except where "
    "otherwise stated. See https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/ "
    "and https://www.legislation.gov.uk/. The official legislation.gov.uk text prevails. "
    "Not legal advice."
)
UA = DEFAULT_UA + " source=https://www.legislation.gov.uk/developer"
HOST = "https://www.legislation.gov.uk"
WORKERS = 8
SLEEP = 0.45
RESULTS = 100
log = logging.getLogger("uk")

NS_ATOM = "http://www.w3.org/2005/Atom"
NS_UKM = "http://www.legislation.gov.uk/namespaces/metadata"
NS_LEG = "http://www.legislation.gov.uk/namespaces/legislation"
NS_DC = "http://purl.org/dc/elements/1.1/"

# Fair use: 3000 / 5 min. Stay under.
_rate_lock = threading.Lock()
_rate_times: list[float] = []


def rate_wait(max_per_5min: int = 2400) -> None:
    global _rate_times
    sleep_for = 0.0
    with _rate_lock:
        now = time.time()
        _rate_times = [t for t in _rate_times if now - t < 300]
        if len(_rate_times) >= max_per_5min:
            sleep_for = 300 - (now - _rate_times[0]) + 0.2
        _rate_times.append(now + max(0.0, sleep_for))
    if sleep_for > 0:
        log.info("rate-limit pause %.1fs", sleep_for)
        time.sleep(sleep_for)


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def https(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


def api_get(url: str, retries: int = 5) -> Optional[object]:
    rate_wait()
    r = http_get(url, ua=UA, sleep=SLEEP, timeout=(20, 120), retries=retries, allow_empty=True)
    if r.status_code in (404, 410):
        return None
    if r.status_code == 403:
        log.warning("HTTP 403 (fair use?) %s", url)
        time.sleep(20)
        return r
    if r.status_code != 200 or not r.content:
        return r
    return r


def catalog_path(kind: str) -> Path:
    return ROOT / CC / "raw" / f"catalog_{kind}.jsonl"


def load_catalog(kind: str) -> list[dict]:
    p = catalog_path(kind)
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


def save_catalog(kind: str, items: list[dict]) -> None:
    atomic_write(catalog_path(kind), "".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items))


def parse_entries(xml_bytes: bytes, kind: str) -> tuple[list[dict], Optional[str], dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    next_href = None
    meta = {}
    for child in list(root):
        tag = localtag(child.tag)
        if tag == "link" and child.attrib.get("rel") == "next":
            next_href = https(child.attrib.get("href") or "")
        if tag == "morePages":
            meta["morePages"] = (child.text or "").strip()
        if tag == "facetType" and child.attrib.get("type"):
            meta["facet_total"] = child.attrib.get("value")
    for entry in root.iter():
        if localtag(entry.tag) != "entry":
            continue
        rec: dict = {"kind": kind}
        xml_url = html_url = pdf_url = ident = title = None
        year = number = None
        published = None
        for el in list(entry):
            t = localtag(el.tag)
            if t == "id":
                ident = (el.text or "").strip()
            elif t == "title":
                title = (el.text or "").strip()
            elif t == "published":
                published = (el.text or "").strip()
            elif t == "link":
                href = https(el.attrib.get("href") or "")
                rel = el.attrib.get("rel") or ""
                typ = el.attrib.get("type") or ""
                if typ == "application/xml" or href.endswith("/data.xml"):
                    xml_url = href
                elif typ == "application/pdf" or "/pdfs/" in href:
                    pdf_url = href
                elif rel in ("", "alternate") and "/data." not in href and ident:
                    html_url = href
            elif t == "Year":
                year = el.attrib.get("Value")
            elif t == "Number":
                number = el.attrib.get("Value")
            elif t == "DocumentMainType":
                rec["main_type"] = el.attrib.get("Value")
        if not ident:
            continue
        rec.update({
            "id": ident,
            "title": title,
            "year": year,
            "number": number,
            "xml_url": xml_url,
            "html_url": html_url,
            "pdf_url": pdf_url,
            "published": published,
        })
        items.append(rec)
    return items, next_href, meta


def discover(kind: str) -> list[dict]:
    existing = load_catalog(kind)
    min_n = 15000 if kind == "ukpga" else 20000
    if existing and len(existing) >= min_n:
        log.info("resume catalog %s n=%s", kind, len(existing))
        return existing
    items: list[dict] = []
    seen: set[str] = set()
    for it in existing:
        k = it.get("id")
        if k:
            seen.add(k)
            items.append(it)
    url = f"{HOST}/{kind}/data.feed?results-count={RESULTS}"
    pages = 0
    while url and pages < 400:
        pages += 1
        resp = api_get(url)
        if not isinstance(resp, type(api_get.__annotations__.get("return")) if False else object):
            pass
        if resp is None or not hasattr(resp, "content"):
            log.warning("catalog page missing %s", url)
            break
        if getattr(resp, "status_code", 200) != 200 or not resp.content:
            log.warning("catalog HTTP %s %s", getattr(resp, "status_code", None), url)
            break
        batch, nxt, meta = parse_entries(resp.content, kind)
        newc = 0
        for it in batch:
            k = it.get("id")
            if not k or k in seen:
                continue
            seen.add(k)
            items.append(it)
            newc += 1
        log.info("catalog %s page=%s batch=%s new=%s total=%s next=%s meta=%s",
                 kind, pages, len(batch), newc, len(items), bool(nxt), meta)
        if pages % 10 == 0:
            save_catalog(kind, items)
        if not batch or not nxt:
            break
        url = nxt if "results-count=" in nxt else (
            nxt + ("&" if "?" in nxt else "?") + f"results-count={RESULTS}"
        )
        # keep results-count
        if "results-count=" not in url:
            url += ("&" if "?" in url else "?") + f"results-count={RESULTS}"
    save_catalog(kind, items)
    log.info("catalog %s done n=%s", kind, len(items))
    return items


def path_from_id(ident: str, kind: str) -> Optional[str]:
    # http://www.legislation.gov.uk/id/ukpga/1980/68  or /id/ukpga/Geo3/41/5
    ident = ident.replace("https://", "http://")
    prefix = f"http://www.legislation.gov.uk/id/{kind}/"
    if ident.startswith(prefix):
        return ident[len(prefix):]
    m = re.search(rf"/id/{kind}/(.+)$", ident)
    return m.group(1) if m else None


def el_text(el: ET.Element, skip: set[str] | None = None) -> str:
    skip = skip or {"Commentary", "CommentaryRef", "Footnote", "Footnotes", "Metadata"}
    if localtag(el.tag) in skip:
        return ""
    parts: list[str] = []
    if el.text and el.text.strip():
        parts.append(el.text.strip())
    for c in list(el):
        t = el_text(c, skip)
        if t:
            parts.append(t)
        if c.tail and c.tail.strip():
            parts.append(c.tail.strip())
    tag = localtag(el.tag)
    if tag in {"P1", "P1para", "P2para", "Text", "Pblock", "P1group"}:
        parts.append("\n")
    return " ".join(parts)


def parse_clml(raw: str, law_id: str, source_url: str, date: Optional[str]) -> tuple[str, str, list[dict], dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        text = xml_to_text(raw)
        return "", text, split_articles(text, law_id, source_url, date), {}
    title = ""
    status = ""
    year = number = None
    for el in root.iter():
        t = localtag(el.tag)
        if t in {"Title", "title"} and not title and (el.text or "").strip():
            # prefer dc:title or LongTitle later
            if "dc" in (el.tag or "") or t == "title":
                title = el.text.strip()
        if t == "DocumentStatus":
            status = el.attrib.get("Value") or ""
        if t == "Year":
            year = el.attrib.get("Value") or year
        if t == "Number":
            number = el.attrib.get("Value") or number
        if t == "LongTitle" and not title:
            title = " ".join(el.itertext()).strip()
    if not title:
        for el in root.iter():
            if localtag(el.tag) in {"Title", "title"} and (el.text or "").strip():
                title = el.text.strip()
                break
    body_text_parts = []
    docs = []
    for el in root.iter():
        if localtag(el.tag) != "P1":
            continue
        num = ""
        for child in list(el):
            if localtag(child.tag) == "Pnumber":
                num = re.sub(r"\s+", " ", "".join(child.itertext())).strip()
                break
        chunk = re.sub(r"[ \t]+", " ", el_text(el))
        chunk = re.sub(r"\n{3,}", "\n\n", chunk).strip()
        if not chunk or len(chunk) < 20:
            continue
        body_text_parts.append(chunk)
        label = f"Section {num}" if num else f"Section {len(docs)+1}"
        aid = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": label,
            "text": chunk,
            "date_filed": date,
            "document_number": label,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num or label,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "clml_p1"}},
        })
        if len(docs) >= 4000:
            break
    text = "\n\n".join(body_text_parts)
    if not text:
        text = xml_to_text(raw, skip_tags={
            "meta", "identification", "references", "classification", "workflow",
            "analysis", "proprietary", "presentation", "commentary", "commentaries",
            "metadata", "primarymetadata", "alternatives",
        })
        if not docs:
            docs = split_articles(text, law_id, source_url, date)
    return title, text, docs, {"status": status, "year": year, "number": number}


def candidate_xml(it: dict, kind: str) -> list[str]:
    urls = []
    key = path_from_id(it.get("id") or "", kind)
    if key:
        urls.append(f"{HOST}/{kind}/{key}/data.xml")
        urls.append(f"{HOST}/{kind}/{key}/enacted/data.xml")
    if it.get("xml_url"):
        urls.append(https(it["xml_url"]))
    # unique
    out = []
    seen = set()
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def fetch_one(it: dict, done: set[str]) -> str:
    ident = it.get("id") or ""
    kind = it.get("kind") or "ukpga"
    key = path_from_id(ident, kind) or ident
    rid = slug_id(CC, f"{kind}-{key}")
    if rid in done:
        return "skip"
    title = it.get("title") or key
    date = iso_date((it.get("published") or "")[:10])
    raw = ""
    source_url = ""
    method = ""
    for url in candidate_xml(it, kind):
        try:
            resp = api_get(url)
        except Exception:
            continue
        if resp is None or not hasattr(resp, "content"):
            continue
        if getattr(resp, "status_code", 0) != 200 or not resp.content:
            continue
        body = resp.content
        if body[:1] == b"<" or b"<Legislation" in body[:2000]:
            raw_try = body.decode(resp.encoding or "utf-8", "replace")
            if "<Legislation" in raw_try or "legislation.gov.uk/namespaces" in raw_try:
                raw = raw_try
                source_url = url
                method = "clml"
                break
    if not raw and key:
        html_url = f"{HOST}/{kind}/{key}/data.htm"
        try:
            resp = api_get(html_url)
        except Exception:
            resp = None
        if resp is not None and getattr(resp, "status_code", 0) == 200 and resp.content:
            html = resp.content.decode(resp.encoding or "utf-8", "replace")
            if not af.is_challenge(html, 200) and len(html_to_text(html)) >= 80:
                raw = html
                source_url = html_url
                method = "html"
    pdf_url = it.get("pdf_url") or ""
    if key and not pdf_url:
        pdf_url = f"{HOST}/{kind}/{key}/pdfs/{kind}_{str(it.get('year') or '')}{str(it.get('number') or '').zfill(4)}_en.pdf"
    if (not raw or method == "html") and pdf_url and "/data.pdf" not in pdf_url:
        try:
            import subprocess, tempfile
            resp = api_get(https(pdf_url))
            if resp is not None and getattr(resp, "status_code", 0) == 200 and resp.content[:4] == b"%PDF":
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
                    tmp.write(resp.content)
                    tmp.flush()
                    proc = subprocess.run(
                        ["pdftotext", "-layout", "-enc", "UTF-8", tmp.name, "-"],
                        check=False, capture_output=True, timeout=120,
                    )
                if proc.returncode == 0 and proc.stdout:
                    raw = proc.stdout.decode("utf-8", "replace")
                    source_url = https(pdf_url)
                    method = "pdf"
        except Exception as exc:
            log.warning("pdf fail %s %s", ident, exc)
    if not raw:
        # Wayback of official latest XML
        if key:
            wb = af.get_wayback_content(f"{HOST}/{kind}/{key}/data.xml")
            if wb.get("status") == "success" and wb.get("text") and "<Legislation" in (wb.get("text") or ""):
                raw = wb["text"]
                source_url = wb.get("wayback_url") or f"{HOST}/{kind}/{key}/data.xml"
                method = "xml_wayback"
    if not raw or len(raw) < 40:
        log_failure(CC, {"id": rid, "url": ident, "status": "failed", "reason": "no_body"})
        return "fail"
    if method in {"clml", "xml_wayback"}:
        parsed_title, text, docs, meta = parse_clml(raw, rid, source_url, date)
        title = parsed_title or title
        status = (meta.get("status") or "").lower()
    else:
        text = html_to_text(raw) if method == "html" else raw
        docs = split_articles(text, rid, source_url, date)
        status = ""
    if not text or len(text) < 40:
        log_failure(CC, {"id": rid, "url": source_url or ident, "status": "failed", "reason": "empty_text"})
        return "fail"
    repealed = "repealed" in (title or "").lower()
    law_status = "repealed" if repealed else ("current" if status in {"revised", "final", ""} else "unknown")
    if status == "revised":
        law_status = "repealed" if repealed else "current"
    canon = f"{HOST}/{kind}/{key}" if key else source_url
    rec = base_record(
        cc=CC, country=COUNTRY, language="en", ident=f"{kind}-{key}", title=title,
        text=text, source_url=source_url or canon, source_type=SOURCE_TYPE,
        license_text=LICENSE, collector="collect_legislation_gov_uk.py",
        eli=ident if ident.startswith("http") else None, date=date,
        official_identifier=f"{kind} {key}".replace("/", " "),
        document_type="statute" if kind == "ukpga" else "regulation",
        law_status=law_status, is_current=(law_status == "current"), documents=docs,
        extra_meta={
            "discovery": {"method": "atom_data.feed", "kind": kind},
            "document_status": status,
            "year": it.get("year"),
            "number": it.get("number"),
            "text_extraction": {"source": "official", "backend": method},
        },
        extra_fields={"canonical_law_url": canon, "information_url": canon},
    )
    rec["id"] = rid
    write_instrument(CC, rec)
    done.add(rid)
    return "ok"


def run_pool(items, done, counters, write_progress):
    if not items:
        return
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
            if n % 40 == 0 or n == len(items):
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), counters["ok"], counters["skip"], counters["fail"])
                write_progress("catalog-backed incomplete")


def main():
    setup()
    t0 = utcnow()
    pga = discover("ukpga")
    counters = {"ok": 0, "skip": 0, "fail": 0}
    source_urls = [
        "https://www.legislation.gov.uk/",
        "https://www.legislation.gov.uk/developer",
        "https://www.legislation.gov.uk/ukpga/data.feed",
        "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
    ]
    all_items = list(pga)
    notes = (
        "UK Public General Acts from legislation.gov.uk CLML (latest/revised "
        "data.xml first). Repealed titles kept with law_status=repealed when "
        "marked. Then UK Statutory Instruments if feasible. Not BAILII/Westlaw. "
        "OGL v3.0. robots.txt: */data.pdf not fetched; /pdfs/ used only when XML absent."
    )

    def write_progress(coverage: str, extra: str = ""):
        write_summary(
            CC, country=COUNTRY,
            source="legislation.gov.uk (The National Archives)",
            source_urls=source_urls, license_text=LICENSE,
            discovered=len(all_items), fetched=counters["ok"], skipped=counters["skip"],
            failed=counters["fail"], coverage=coverage, notes=notes + extra,
        )

    done = existing_ids(CC)
    log.info("queue ukpga=%s already_done=%s", len(pga), len(done))
    run_pool(pga, done, counters, write_progress)
    log.info("ukpga phase done ok=%s skip=%s fail=%s", counters["ok"], counters["skip"], counters["fail"])

    # SIs if PGA mostly succeeded
    if counters["ok"] + counters["skip"] >= max(50, int(0.3 * max(1, len(pga)))):
        try:
            si = discover("uksi")
            all_items.extend(si)
            done = existing_ids(CC)
            log.info("queue uksi=%s already_done=%s", len(si), len(done))
            run_pool(si, done, counters, write_progress)
        except Exception as exc:
            log.warning("uksi phase failed: %s", exc)

    cov = "full" if counters["fail"] == 0 and counters["ok"] + counters["skip"] >= len(all_items) else "catalog-backed incomplete"
    write_progress(cov, extra=f" Started {t0}.")
    log.info("done ok=%s skip=%s fail=%s coverage=%s", counters["ok"], counters["skip"], counters["fail"], cov)


if __name__ == "__main__":
    main()
