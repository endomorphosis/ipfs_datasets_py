#!/usr/bin/env python3
"""Bulgaria: State Gazette (dv.parliament.bg) RSS + materiali.faces issue HTML."""
from __future__ import annotations
import json, logging, re, sys
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "bg", "Bulgaria", "dv_parliament"
LICENSE = "State Gazette of the Republic of Bulgaria (dv.parliament.bg). Official texts; reuse per public-sector / gazette terms."
UA = DEFAULT_UA + " source=https://dv.parliament.bg/"
BASE = "https://dv.parliament.bg/DVWeb/"
log = logging.getLogger("bg")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def discover() -> list[dict]:
    items, seen = [], set()
    # official RSS of latest official-section materials
    r = http_get(BASE + "rss_newspaper.jsp", ua=UA, sleep=0.3, headers={"Accept": "application/rss+xml, application/xml, text/xml"})
    if r.status_code == 200 and r.content:
        (ROOT / CC / "raw" / "rss_newspaper.xml").write_bytes(r.content)
        text = r.content.decode("utf-8", "replace")
        for m in re.finditer(r"<item>([\s\S]*?)</item>", text):
            block = m.group(1)
            title = re.search(r"<title>([\s\S]*?)</title>", block)
            desc = re.search(r"<description>([\s\S]*?)</description>", block)
            link = re.search(r"<link>([\s\S]*?)</link>", block)
            cat = re.search(r"<category>([\s\S]*?)</category>", block)
            href = (link.group(1).strip() if link else "")
            href = urljoin(BASE, href)
            rec = {
                "title": (title.group(1).strip() if title else ""),
                "description": (desc.group(1).strip() if desc else ""),
                "url": href,
                "category": (cat.group(1).strip() if cat else ""),
            }
            if href and href not in seen:
                seen.add(href); items.append(rec); append_catalog(CC, rec)
    # homepage + search pages
    for seed in (BASE + "index.faces", BASE + "searchDV.faces", BASE + "broeveList.faces"):
        r = http_get(seed, ua=UA, sleep=0.4)
        if r.status_code != 200:
            continue
        (ROOT / CC / "raw" / re.sub(r"[^a-zA-Z0-9]+","_", seed)[:80]).write_bytes(r.content[:50000])
        for href in re.findall(r'href="([^"]*materiali\.faces[^"]*)"', r.text):
            href = urljoin(seed, href)
            if href not in seen:
                seen.add(href); rec={"url": href, "title": "", "description": "", "category": ""}; items.append(rec); append_catalog(CC, rec)
        for href in re.findall(r'href="([^"]*(?:showMaterial|material)[^"]*)"', r.text, re.I):
            href = urljoin(seed, href)
            if href.startswith("http") and href not in seen:
                seen.add(href); rec={"url": href, "title": "", "description": "", "category": ""}; items.append(rec); append_catalog(CC, rec)
    # sequential idObj around latest RSS id if present
    ids = []
    for it in items:
        qs = parse_qs(urlparse(it["url"]).query)
        if qs.get("idObj"):
            try:
                ids.append(int(qs["idObj"][0]))
            except Exception:
                pass
    if ids:
        latest = max(ids)
        for i in range(max(1, latest - 400), latest + 5):
            href = urljoin(BASE, f"materiali.faces?idObj={i}")
            if href not in seen:
                seen.add(href); rec={"url": href, "title": "", "description": "", "category": "idObj"}; items.append(rec)
    log.info("discovered %s", len(items))
    return items


def fetch_one(row: dict, done: set[str]) -> str:
    url = row["url"]
    ident = re.sub(r"^https?://", "", url)
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    r = http_get(url, ua=UA, sleep=0.45, retries=2, headers={"Accept": "text/html"})
    if r.status_code != 200 or not r.content or len(r.content) < 400:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": f"http_{getattr(r,'status_code',0)}"})
        return "fail"
    text = html_to_text(r.text)
    if len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_or_chrome"})
        return "fail"
    title = row.get("title") or ident
    m = re.search(r"<title>([^<]+)</title>", r.text, re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    if row.get("description") and len(row["description"]) > len(title):
        title = row["description"][:240]
    rec = base_record(
        cc=CC, country=COUNTRY, language="bg", ident=ident, title=title, text=text,
        source_url=url, source_type=SOURCE_TYPE, license_text=LICENSE, collector="bg-dv-html",
        eli=None, date=None, official_identifier=ident, document_type="gazette_act",
        law_status="unknown", is_current=None,
        extra_meta={"discovery": {"method": "rss_and_materiali", "category": row.get("category")}},
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup(); t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for it in items:
        try:
            st = fetch_one(it, done)
        except Exception as exc:
            st = "fail"
            log_failure(CC, {"status": "failed", "reason": repr(exc)})
        ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
        if st == "ok":
            done.add(slug_id(CC, re.sub(r"^https?://", "", it["url"])))
        if (ok + fail) % 40 == 0 and (ok + fail):
            log.info("ok=%s fail=%s / %s", ok, fail, len(items))
    notes = (
        "Official JSF portal has no public bulk/open-data dump. Harvested official RSS "
        "(rss_newspaper.jsp) plus materiali.faces issue pages and a bounded idObj window around the latest issue. "
        "Full historical catalog requires the JSF postback search (broeveList.faces) which is session/ViewState gated."
    )
    write_summary(CC, country=COUNTRY, source="Държавен вестник (dv.parliament.bg)",
                  source_urls=["https://dv.parliament.bg/", "https://dv.parliament.bg/DVWeb/rss_newspaper.jsp",
                               "https://dv.parliament.bg/DVWeb/broeveList.faces"],
                  license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                  coverage="shard" if ok else "catalog-backed incomplete",
                  notes=notes, last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(items), ok, fail)


if __name__ == "__main__":
    main()
