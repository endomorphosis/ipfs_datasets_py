#!/usr/bin/env python3
"""Sweden: Svensk författningssamling via Riksdagen öppna data."""
from __future__ import annotations

import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC = "se"
COUNTRY = "Sweden"
SOURCE_TYPE = "riksdagen_sfs"
LICENSE = (
    "Riksdagens öppna data: CC0 1.0 (public domain dedication) as stated at "
    "https://www.riksdagen.se/sv/dokument-och-lagar/riksdagens-oppna-data/ "
    "and https://www.riksdagen.se/sv/dokument-och-lagar/riksdagens-oppna-data/anvandarstod/villkor-for-anvandning/"
)
UA = DEFAULT_UA + " source=https://data.riksdagen.se/"
WORKERS = 6
SLEEP = 0.2
log = logging.getLogger("se")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                  logging.StreamHandler(sys.stdout)],
    )


def discover() -> list[dict]:
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    items = []
    if cat.exists() and cat.stat().st_size > 1000:
        with cat.open(encoding="utf-8") as f:
            for line in f:
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        if items:
            log.info("resume catalog %s", len(items))
            return items
    seen = set()
    page = 1
    stagnant = 0
    while page <= 400:
        url = f"https://data.riksdagen.se/dokumentlista/?doktyp=sfs&utformat=json&sz=100&p={page}"
        r = http_get(url, ua=UA, sleep=0.15)
        r.raise_for_status()
        data = r.json()
        dl = data.get("dokumentlista") or {}
        docs = dl.get("dokument") or []
        if isinstance(docs, dict):
            docs = [docs]
        newc = 0
        for d in docs:
            did = d.get("id") or d.get("dok_id")
            if not did or did in seen:
                continue
            seen.add(did)
            items.append(d)
            append_catalog(CC, d)
            newc += 1
        log.info("catalog page=%s new=%s total=%s traffar=%s", page, newc, len(items), dl.get("@traffar"))
        if newc == 0:
            stagnant += 1
            if stagnant >= 2:
                break
        else:
            stagnant = 0
        page += 1
    return items


def fetch_one(it: dict, done: set[str]) -> str:
    did = (it.get("id") or it.get("dok_id") or "").lower()
    if not did:
        return "fail"
    rid = slug_id(CC, did)
    if rid in done:
        return "skip"
    text_url = f"https://data.riksdagen.se/dokument/{did}.text"
    html_url = f"https://data.riksdagen.se/dokument/{did}.html"
    text = ""
    src = text_url
    r2 = http_get(text_url, ua=UA, sleep=SLEEP, allow_empty=True, retries=2, headers={"Accept": "text/plain, */*"})
    if r2.status_code == 200 and r2.text.strip() and b"Server Error" not in r2.content[:200]:
        text = r2.text.strip()
    if not text:
        r = http_get(html_url, ua=UA, sleep=SLEEP, allow_empty=True, retries=2, headers={"Accept": "text/html, */*"})
        if r.status_code == 200 and r.content and b"Server Error" not in r.content[:200] and len(r.content) > 40:
            text = html_to_text(r.text)
            src = html_url
    if not text:
        log_failure(CC, {"identifier": did, "source_url": html_url, "status": "failed", "reason": "empty_text"})
        return "fail"
    title = it.get("titel") or it.get("dokumentnamn") or did
    status_raw = (it.get("status") or "").lower()
    if "upphäv" in status_raw or "upphav" in status_raw:
        law_status, is_cur = "repealed", False
    elif status_raw in ("", "gäller", "gällande"):
        law_status, is_cur = "current", True
    else:
        law_status, is_cur = "unknown", None
    rec = base_record(
        cc=CC, country=COUNTRY, language="sv", ident=did, title=title, text=text,
        source_url=f"https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/{did}",
        source_type=SOURCE_TYPE, license_text=LICENSE, collector="se-riksdagen-sfs",
        eli=None, date=iso_date(it.get("datum") or it.get("publicerad")),
        official_identifier=it.get("beteckning") or did,
        document_type="statute", law_status=law_status, is_current=is_cur,
        extra_meta={"discovery": {"method": "dokumentlista_sfs", "dok_id": did},
                    "official_metadata": {k: it.get(k) for k in ("organ", "nummer", "rm", "typ", "subtyp", "status", "beteckning") if it.get(k)}},
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup()
    t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
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
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            if n % 200 == 0:
                log.info("progress %s/%s ok=%s skip=%s fail=%s", n, len(items), ok, skip, fail)
                write_summary(CC, country=COUNTRY, source="Riksdagen öppna data / SFS",
                              source_urls=["https://data.riksdagen.se/", "https://svenskforfattningssamling.se/"],
                              license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes="SFS via dokumentlista", last_run=utcnow())
    coverage = "full" if fail == 0 and ok + skip >= len(items) else "catalog-backed incomplete"
    write_summary(CC, country=COUNTRY, source="Riksdagen öppna data / Svensk författningssamling",
                  source_urls=["https://data.riksdagen.se/", "https://www.riksdagen.se/sv/dokument-och-lagar/riksdagens-oppna-data/"],
                  license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                  coverage=coverage, notes="All SFS documents from dokumentlista doktyp=sfs. CC0 as stated by Riksdagen.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
