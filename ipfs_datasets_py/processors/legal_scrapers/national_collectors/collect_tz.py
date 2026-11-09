#!/usr/bin/env python3
"""Tanzania: Parliament/POLIS acts + OAG MIS official PDFs.

Official only:
  https://www.parliament.go.tz/acts  (DataTables -> polis.bunge.go.tz/api/acts/async)
  https://polis.bunge.go.tz/uploads/bills/acts/*.pdf
  https://oagmis.oag.go.tz/portal/acts-ajax (+ /portal/acts/{id}/download)
  https://oagmis.oag.go.tz/portal/revised-acts-ajax (+ /portal/acts/revised/{id}/download)
  https://www.parliament.go.tz/documents/constitution-of-tanzania

No commercial DBs / AfricanLII-as-source / tanzanialaws.com. No WAF bypass.
Wayback/CDX of official .go.tz URLs OK via fetch_official.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    first_title,
    live_get,
    save_instrument,
    setup_log,
    slug_id,
)

CC, COUNTRY, LANG = "tz", "Tanzania", "en"
SOURCE_TYPE = "bunge_oag"
LICENSE = (
    "Acts of the Parliament of the United Republic of Tanzania as published on "
    "parliament.go.tz / polis.bunge.go.tz / oagmis.oag.go.tz. Government Printer "
    "gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.parliament.go.tz/)"
ART = re.compile(r"(?im)^\s*((?:Section|Article|Part|CHAPTER)\s+[0-9IVXLC]+[A-Za-z]?)\b")
log = logging.getLogger("tz")

POLIS_API = "https://polis.bunge.go.tz/api/acts/async"
POLIS_BASE = "https://polis.bunge.go.tz"
OAG_ACTS_AJAX = "https://oagmis.oag.go.tz/portal/acts-ajax"
OAG_REV_AJAX = "https://oagmis.oag.go.tz/portal/revised-acts-ajax"
CONST_PAGE = "https://www.parliament.go.tz/documents/constitution-of-tanzania"
CONST_PDF_HINT = re.compile(
    r'href="(https://www\.parliament\.go\.tz/uploads/documents/[^"]+\.pdf)"',
    re.I,
)


def _norm_title(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    return s.strip()[:120]


def _json_get(url: str) -> dict | list | None:
    try:
        r = live_get(url, ua=UA, verify=False, timeout=(20, 90), retries=3)
        if r.status_code != 200 or not r.content:
            log.info("json HTTP %s %s", r.status_code, url)
            return None
        return json.loads(r.content.decode(r.encoding or "utf-8", "replace"))
    except Exception as exc:
        log.info("json fail %s: %s", url, exc)
        return None


def discover() -> list[dict]:
    """Return prioritized catalog rows: {ident, url, title, source, date}."""
    items: list[dict] = []
    seen_url: set[str] = set()
    seen_title: set[str] = set()

    def add(*, ident: str, url: str, title: str, source: str, date: str | None = None, priority: int = 50, wayback_ts: str | None = None):
        url = (url or "").split("#")[0].strip()
        if not url.startswith("http"):
            return
        # space-escape for PDF paths with spaces
        if " " in url and "%20" not in url:
            # quote path carefully
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(url)
            path = quote(parts.path, safe="/%")
            url = urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
        if url in seen_url:
            return
        nt = _norm_title(title)
        # soft title dedupe across sources (keep higher-priority first)
        if nt and nt in seen_title and len(nt) > 20:
            return
        seen_url.add(url)
        if nt and len(nt) > 20:
            seen_title.add(nt)
        items.append({
            "ident": ident[:160],
            "url": url,
            "title": (title or ident)[:240],
            "source": source,
            "date": date,
            "priority": priority,
            "wayback_ts": wayback_ts,
        })

    # 1) Constitution (highest priority)
    try:
        r = live_get(CONST_PAGE, ua=UA, verify=True, timeout=(15, 40))
        if r.status_code == 200 and r.text:
            m = CONST_PDF_HINT.search(r.text)
            if m:
                add(
                    ident="constitution-1977-katiba",
                    url=m.group(1),
                    title="Katiba ya Jamhuri ya Muungano wa Tanzania ya Mwaka 1977 (Constitution)",
                    source="parliament_constitution",
                    date="1977",
                    priority=0,
                )
    except Exception as exc:
        log.info("constitution page: %s", exc)

    # known constitution PDF fallback if page scrape missed
    if not any(x["source"] == "parliament_constitution" for x in items):
        add(
            ident="constitution-1977-katiba",
            url=(
                "https://www.parliament.go.tz/uploads/documents/"
                "sw-1761661604-KATIBA YA JAMHURI YA MUUNGANO WA TANZANIA YA MWAKA 1977 (2).pdf"
            ),
            title="Katiba ya Jamhuri ya Muungano wa Tanzania ya Mwaka 1977 (Constitution)",
            source="parliament_constitution",
            date="1977",
            priority=0,
        )

    # 2) OAG revised acts (consolidations)
    rev = _json_get(OAG_REV_AJAX)
    if isinstance(rev, dict) and isinstance(rev.get("data"), list):
        for row in rev["data"]:
            rid = row.get("id")
            if rid is None:
                continue
            title = (row.get("shortTitle") or f"Revised Act {rid}").strip()
            chap = row.get("chapterNumber")
            if chap:
                title = f"{title} (Cap. {chap})"
            add(
                ident=f"oag-rev-{rid}",
                url=f"https://oagmis.oag.go.tz/portal/acts/revised/{rid}/download",
                title=title,
                source="oag_revised",
                date=(row.get("publicationDate") or "")[:10] or None,
                priority=10,
            )
        log.info("oag revised catalog %s", len(rev["data"]))

    # 3) OAG parliament acts
    acts = _json_get(OAG_ACTS_AJAX)
    if isinstance(acts, dict) and isinstance(acts.get("data"), list):
        for row in acts["data"]:
            aid = row.get("id")
            if aid is None:
                continue
            title = (row.get("shortTitle") or row.get("longTitle") or f"Act {aid}").strip()
            add(
                ident=f"oag-act-{aid}",
                url=f"https://oagmis.oag.go.tz/portal/acts/{aid}/download",
                title=title,
                source="oag_acts",
                date=(row.get("enactmentDate") or row.get("publicationDate") or "")[:10] or None,
                priority=20,
            )
        log.info("oag acts catalog %s", len(acts["data"]))

    # 4) POLIS / Bunge acts API (broader shelf)
    polis = _json_get(POLIS_API)
    if isinstance(polis, dict) and isinstance(polis.get("data"), list):
        for row in polis["data"]:
            pid = row.get("id")
            file_url = row.get("file_url") or ""
            if not pid or not file_url:
                continue
            if not file_url.startswith("http"):
                file_url = urljoin(POLIS_BASE + "/", file_url.lstrip("/"))
            title = (row.get("title_en") or row.get("title_sw") or f"Act {pid}").strip()
            act_no = (row.get("act_no") or "").strip()
            if act_no and act_no.lower() not in title.lower():
                title = f"{title} ({act_no})"
            add(
                ident=f"polis-act-{pid}",
                url=file_url,
                title=title,
                source="polis_acts",
                date=(row.get("posted") or row.get("created_at") or "")[:10] or None,
                priority=30,
            )
        log.info("polis catalog %s", len(polis["data"]))

    # 5) CDX of official PDF hosts (gap-fill when live APIs thin)
    for prefix in (
        "polis.bunge.go.tz/uploads/bills/acts/",
        "www.parliament.go.tz/uploads/",
        "www.parliament.go.tz/assets/uploads/files/",
        "parliament.go.tz/assets/uploads/files/",
        "oagmis.oag.go.tz/portal/acts/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 150), match_type="prefix"):
            orig = h.get("original") or ""
            if not orig or not (".pdf" in orig.lower() or re.search(r"/acts/\d+/download", orig)):
                continue
            stem = Path(orig.split("?")[0]).stem[:120]
            add(
                ident=f"cdx-{stem}",
                url=orig,
                title=stem.replace("-", " ").replace("_", " "),
                source="cdx_official",
                priority=80,
                wayback_ts=h.get("timestamp"),
            )

    items.sort(key=lambda x: (x["priority"], x["ident"]))

    # persist catalog
    cat = ROOT / CC / "raw" / "catalog.jsonl"
    cat.parent.mkdir(parents=True, exist_ok=True)
    with cat.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 100)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    catalog = discover()
    for row in catalog:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        ident = row["ident"]
        url = row["url"]
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=150, wayback_ts=row.get("wayback_ts"))
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {
                "identifier": ident,
                "source_url": url,
                "reason": got.get("error"),
                "catalog_source": row.get("source"),
            })
            continue
        # Retain upstream statute-quality checks, including authentic Swahili bodies.
        if not re.search(r"\b(Section|PART|Act|ACT|United Republic|Tanzania|Sheria|Katiba|Jamhuri)\b", text):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "not_act_like"})
            continue
        title = row.get("title") or first_title(text, ident)
        # prefer a strong title line from the PDF when catalog title is thin
        if len(title) < 20:
            title = first_title(text, title)
        extra = {
            "fetch_method": got.get("method"),
            "catalog_source": row.get("source"),
            "retrieval": "live" if str(got.get("method") or "").startswith("http") else "wayback",
        }
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_tz.py",
            date=row.get("date"),
            article_re=ART,
            extra_meta=extra,
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s src=%s method=%s chars=%s", ident[:70], row.get("source"), got.get("method"), len(text))
        else:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "save_failed"})
    write_summary(
        CC,
        country=COUNTRY,
        source="Parliament of Tanzania / POLIS / OAG MIS",
        source_urls=[
            "https://www.parliament.go.tz/acts",
            "https://polis.bunge.go.tz/api/acts/async",
            "https://oagmis.oag.go.tz/portal/acts",
            "https://oagmis.oag.go.tz/portal/revised-acts",
        ],
        license_text=LICENSE,
        discovered=len(catalog),
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete",
        notes=(
            "Official Bunge/POLIS/OAG only. Live PDFs (+ Wayback of official URLs on fail). "
            "Not tanzanialaws.com. Not AfricanLII. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s catalog=%s", ok, skip, fail, len(catalog))


if __name__ == "__main__":
    main()
