#!/usr/bin/env python3
"""Tanzania: Parliament/POLIS acts + OAG MIS official PDFs.

Official only:
  https://www.parliament.go.tz/acts  (DataTables -> polis.bunge.go.tz/api/acts/async)
  https://polis.bunge.go.tz/uploads/bills/acts/*.pdf
  https://oagmis.oag.go.tz/portal/acts-ajax (+ /portal/acts/{id}/download)
  https://oagmis.oag.go.tz/portal/revised-acts-ajax (+ /portal/acts/revised/{id}/download)
  https://www.parliament.go.tz/documents/constitution-of-tanzania

Densify: Tanzania Acts use Commonwealth ``1. Short title.`` section numbering
(not only ``Section N`` / ``Part N``). Prefer enacting body after ``BE IT ENACTED``
/ ARRANGEMENT OF SECTIONS TOC to avoid double-counting.

No commercial DBs / AfricanLII-as-source / tanzanialaws.com. No WAF bypass.
Wayback/CDX of official .go.tz URLs OK via fetch_official.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    INDEX_FIELDS,
    ROOT,
    atomic_write,
    base_record,
    existing_ids,
    log_failure,
    utcnow,
    write_instrument,
    write_summary,
)
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    first_title,
    live_get,
    setup_log,
    slug_id,
    split_custom,
)

CC, COUNTRY, LANG = "tz", "Tanzania", "en"
SOURCE_TYPE = "bunge_oag"
LICENSE = (
    "Acts of the Parliament of the United Republic of Tanzania as published on "
    "parliament.go.tz / polis.bunge.go.tz / oagmis.oag.go.tz. Government Printer "
    "gazette text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.parliament.go.tz/)"

# Commonwealth body: "1. Short title." / "12A. Interpretation." PLUS classic Section/Article/Part
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|Cap\.?|Chapter|Part)\s*[0-9IVXLC]+[A-Za-z]?|"
    r"\d+[A-Za-z]?\.)(?=\s*(?:[A-Z\"'(]|In |This |These |The |For |Kut|Eneo|Haki|Usawa|Serikali|Matumizi|Ufafanuzi|Ujenzi|Nafasi))"
)
ART_ONLY = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+[A-Za-z]?)\b")

ACT_TEXT_RE = re.compile(
    r"(?i)(?:BE IT ENACTED|ARRANGEMENT OF SECTIONS|AN ACT\b|A BILL\b|"
    r"This Act may be cited|Short title|I assent|Date of commencement|"
    r"CHAPTER\s+\d+|Cap\.\s*\d+|Katiba|CONSTITUTION|"
    r"THE\s+[A-Z][A-Z0-9 \-',()]{6,100}\s+ACT)"
)
ACT_URL_RE = re.compile(
    r"(?i)(?:oagmis\.oag\.go\.tz|polis\.bunge\.go\.tz|parliament\.go\.tz|"
    r"/acts?/|revised|constitution|katiba|_act\.|act\.pdf)"
)

MAX_PDF_BYTES = 8 * 1024 * 1024

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


def prefer_enacting_body(text: str) -> str:
    """Skip arrangement/TOC so article split targets operative sections."""
    if not text:
        return text

    m = re.search(r"(?is)BE IT ENACTED[^\n]*\n", text)
    if m and m.end() < len(text) - 200:
        rest = text[m.end() :]
        arr = re.search(r"(?i)ARRANGEMENT OF (?:SECTIONS|RULES|ORDERS)", rest[:2500])
        if not arr:
            return rest
        text = rest

    body_ones = list(
        re.finditer(
            r"(?im)^\s*1\.\s*(?:This Act|In this Act|These Regulations|These regulations|"
            r"Unless the context|For the purposes)\b",
            text,
        )
    )
    if body_ones:
        return text[body_ones[-1].start() :] if len(body_ones) >= 2 else text[body_ones[0].start() :]

    ones = list(
        re.finditer(
            r"(?im)^\s*1\.\s+(?:Short title|Citation|Interpretation|Definitions)\b",
            text,
        )
    )
    if len(ones) >= 2:
        return text[ones[1].start() :]
    if len(ones) == 1:
        arr = re.search(r"(?i)ARRANGEMENT OF", text)
        if arr and ones[0].start() > arr.start():
            return text[ones[0].start() :]

    m = re.search(r"(?i)ARRANGEMENT OF (?:SECTIONS|RULES|ORDERS)|Arrangement of Sections", text)
    if m:
        after = text[m.end() :]
        body = list(
            re.finditer(
                r"(?im)^\s*1\.\s+(?:Short title|Citation|Interpretation|Definitions|"
                r"This Act|In this Act)\b",
                after,
            )
        )
        if len(body) >= 2:
            return after[body[-1].start() :]
        chapters = list(re.finditer(r"(?im)^\s*CHAPTER\s+(?:I|1)\b", text))
        if len(chapters) >= 2:
            return text[chapters[1].start() :]
        parts = list(re.finditer(r"(?im)^\s*PART\s+I\b", after))
        if len(parts) >= 2:
            return after[parts[1].start() :]
        if body:
            return after[body[0].start() :]
    return text


def split_tz_articles(text: str, rid: str, source_url: str, date=None) -> list:
    """Commonwealth ``1. Title.`` body split by default; constitutions prefer Article N."""
    body = prefer_enacting_body(text)
    docs_sec = split_custom(body, rid, source_url, date, ART)
    docs_art = split_custom(body, rid, source_url, date, ART_ONLY)
    blob = f"{rid}|{source_url}"
    is_const = bool(re.search(r"(?i)constitution|katiba", blob)) and not bool(
        re.search(r"(?i)amm?endment", blob)
    )
    if is_const:
        if len(docs_art) >= 20:
            return docs_art
        if len(docs_art) >= 2 and len(docs_sec) > max(20, len(docs_art) * 3):
            return docs_art
        # Katiba reprints use bare ``1. Kutangaza…`` (not Article N)
        if len(docs_art) < 2:
            return docs_sec if docs_sec else docs_art
    if len(docs_art) >= 50 and len(docs_art) > len(docs_sec) * 1.2:
        return docs_art
    return docs_sec


def save_tz_instrument(
    *,
    ident: str,
    title: str,
    text: str,
    source_url: str,
    date: str | None = None,
    extra_meta: dict | None = None,
) -> bool:
    if not text or len(text) < 80:
        return False
    rid = slug_id(CC, ident)
    docs = split_tz_articles(text, rid, source_url, date)
    meta = {
        "fetch_method": (extra_meta or {}).get("fetch_method"),
        "article_split": "commonwealth-body",
    }
    if extra_meta:
        meta.update(extra_meta)
    rec = base_record(
        cc=CC,
        country=COUNTRY,
        language=LANG,
        ident=ident,
        title=title or first_title(text, ident),
        text=text,
        source_url=source_url,
        source_type=SOURCE_TYPE,
        license_text=LICENSE,
        collector="collect_tz.py",
        date=date,
        documents=docs,
        extra_meta=meta,
    )
    write_instrument(CC, rec)
    return True


def reprocess_existing() -> int:
    """Re-split articles on Act-like instruments with Commonwealth section regex."""
    inst = ROOT / CC / "instruments"
    improved = 0
    for p in sorted(inst.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if len(text) < 200:
            continue
        name = p.name
        blob = f"{name}|{rec.get('title') or ''}|{rec.get('source_url') or ''}|{text[:3000]}"
        if not (ACT_TEXT_RE.search(blob) or ACT_URL_RE.search(blob)):
            continue
        rid = rec.get("id") or p.stem
        url = rec.get("source_url") or ""
        date = rec.get("date")
        docs = split_tz_articles(text, rid, url, date)
        old = int(rec.get("article_count") or len(rec.get("documents") or []) or 0)
        new = len(docs)
        if new <= old and old > 0:
            continue
        if new < 2 and old >= new:
            continue
        rec["documents"] = docs
        rec["article_count"] = new
        rec["article_extraction_status"] = "ok" if docs else "missing"
        meta = rec.get("metadata") or {}
        meta["article_reprocess"] = "collect_tz.py-commonwealth-sections"
        meta["article_split"] = "commonwealth-body"
        rec["metadata"] = meta
        atomic_write(p, json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        improved += 1
        log.info("reprocess %s %s->%s", rid[:70], old, new)
    return improved


def rebuild_index() -> int:
    inst = ROOT / CC / "instruments"
    rows = []
    for p in sorted(inst.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        line = {k: rec.get(k) for k in INDEX_FIELDS if k not in ("path", "bytes", "article_count")}
        line["path"] = f"instruments/{p.name}"
        line["article_count"] = rec.get("article_count") or len(rec.get("documents") or [])
        line["bytes"] = p.stat().st_size
        line["id"] = rec.get("id") or p.stem
        rows.append(line)
    out = ROOT / CC / "index.jsonl"
    atomic_write(out, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    log.info("rebuilt index lines=%s", len(rows))
    return len(rows)


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

    def add(*, ident: str, url: str, title: str, source: str, date: str | None = None, priority: int = 50):
        url = (url or "").split("#")[0].strip()
        if not url.startswith("http"):
            return
        if " " in url and "%20" not in url:
            from urllib.parse import urlsplit, urlunsplit

            parts = urlsplit(url)
            path = quote(parts.path, safe="/%")
            url = urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
        if url in seen_url:
            return
        nt = _norm_title(title)
        if nt and nt in seen_title and len(nt) > 20:
            return
        seen_url.add(url)
        if nt and len(nt) > 20:
            seen_title.add(nt)
        items.append(
            {
                "ident": ident[:160],
                "url": url,
                "title": (title or ident)[:240],
                "source": source,
                "date": date,
                "priority": priority,
            }
        )

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
        "oagmis.oag.go.tz/portal/acts/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 150), match_type="prefix"):
            orig = h.get("original") or ""
            if not orig or ".pdf" not in orig.lower():
                continue
            stem = Path(orig.split("?")[0]).stem[:120]
            add(
                ident=f"cdx-{stem}",
                url=orig,
                title=stem.replace("-", " ").replace("_", " "),
                source="cdx_official",
                priority=80,
            )

    items.sort(key=lambda x: (x["priority"], x["ident"]))

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
    max_new = env_int("MAX_NEW", 40)
    max_seconds = env_int("MAX_SECONDS", 3600)
    do_reprocess = os.environ.get("REPROCESS", "1") not in ("0", "false", "no")
    t_start = time.time()

    reproc_n = 0
    if do_reprocess:
        reproc_n = reprocess_existing()
        rebuild_index()
        log.info("reprocess improved=%s", reproc_n)

    done = existing_ids(CC)
    ok = skip = fail = 0
    catalog: list[dict] = []

    if max_new > 0:
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
            got = fetch_official(url, ua=UA, verify=False, min_text=150)
            text = got.get("text") or ""
            # lean: skip oversized payloads (raw bytes hint if present)
            raw_bytes = got.get("raw_bytes") or got.get("content_length") or 0
            try:
                raw_bytes = int(raw_bytes)
            except Exception:
                raw_bytes = 0
            if raw_bytes and raw_bytes > MAX_PDF_BYTES:
                log.info("skip >8MB sz=%s %s", raw_bytes, ident[:60])
                skip += 1
                continue
            if got.get("status") != "success":
                fail += 1
                log_failure(
                    CC,
                    {
                        "identifier": ident,
                        "source_url": url,
                        "reason": got.get("error"),
                        "catalog_source": row.get("source"),
                    },
                )
                continue
            if len(text) > 2_000_000:
                log.info("skip huge text chars=%s %s", len(text), ident[:60])
                skip += 1
                continue
            title = row.get("title") or first_title(text, ident)
            if len(title) < 20:
                title = first_title(text, title)
            extra = {
                "fetch_method": got.get("method"),
                "catalog_source": row.get("source"),
                "retrieval": "live" if str(got.get("method") or "").startswith("http") else "wayback",
                "article_split": "commonwealth-body",
            }
            if save_tz_instrument(
                ident=ident,
                title=title,
                text=text,
                source_url=url,
                date=row.get("date"),
                extra_meta=extra,
            ):
                ok += 1
                done.add(rid)
                log.info(
                    "ok %s src=%s method=%s chars=%s",
                    ident[:70],
                    row.get("source"),
                    got.get("method"),
                    len(text),
                )
            else:
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": "save_failed"})
        rebuild_index()

    n_inst = rebuild_index()
    arts = 0
    for line in (ROOT / CC / "index.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            arts += int(json.loads(line).get("article_count") or 0)

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
            f"Official Bunge/POLIS/OAG only. Commonwealth 1. Short title. split + "
            f"enacting-body prefer. reprocess_improved={reproc_n} instruments={n_inst} "
            f"articles={arts}. Not tanzanialaws.com. Not AfricanLII. Not legal advice."
        ),
        last_run=t0,
    )
    log.info(
        "done ok=%s skip=%s fail=%s catalog=%s reprocess=%s inst=%s arts=%s",
        ok,
        skip,
        fail,
        len(catalog),
        reproc_n,
        n_inst,
        arts,
    )


if __name__ == "__main__":
    main()
