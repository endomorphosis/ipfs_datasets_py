#!/usr/bin/env python3
"""Namibia: official Acts / Bills / Gazette PDFs via *.gov.na + parliament.na.

Official hosts only: parliament.gov.na, laws.parliament.na, parliament.na,
gov.na, moj.gov.na, opm.gov.na and other *.gov.na gazette hosts.
Not AfricanLII / NamibLII / lac.org.na / commercial DBs as source text.
No WAF bypass. Live-first; Wayback/CDX of official URLs OK (pass CDX timestamps).

Densify: Namibia Acts use Commonwealth ``1. Definitions`` / ``1. Short title.``
section numbering (not only ``Section N`` / ``PART N``). Prefer enacting body
after BE IT ENACTED / ARRANGEMENT OF SECTIONS to avoid TOC double-count
(Namibia often places the arrangement *after* the enacting formula).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    INDEX_FIELDS,
    ROOT,
    atomic_write,
    base_record,
    existing_ids,
    http_get,
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
    setup_log,
    slug_id,
    split_custom,
)

CC, COUNTRY, LANG = "na", "Namibia", "en"
SOURCE_TYPE = "namibia_official_gazette_acts"
LICENSE = (
    "Republic of Namibia — Parliament (parliament.gov.na / laws.parliament.na / "
    "parliament.na) / Government Portal (gov.na) / Ministry of Justice (moj.gov.na) / "
    "Office of the Prime Minister (opm.gov.na) and other *.gov.na gazette hosts. "
    "Authentic Government Gazette / Act text prevails. "
    "Not AfricanLII / NamibLII / lac.org.na / commercial DBs. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.parliament.gov.na/)"

# Commonwealth body: "1. Definitions" / "12A. Interpretation." / margin "Definitions.  1. In this Act"
# PLUS classic Section/Article/Regulation N
ART = re.compile(
    r"(?im)^\s*(?:[A-Z][A-Za-z0-9 \-]{1,45}\.\s+)?"
    r"((?:Article|Art\.?|Section|Sec\.?|Regulation|Reg\.)\s+[0-9]+[A-Za-z]?|"
    r"\d+[A-Za-z]?\.)"
    r"(?=\s+(?:[A-Z\"'(]|In |This |These |The |For ))"
)
ART_ONLY = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+[A-Za-z]?)\b")

ACT_TEXT_RE = re.compile(
    r"(?i)(AN ACT\b|A BILL\b|BE IT ENACTED|ARRANGEMENT OF|"
    r"This Act (?:may be cited|is called|shall be called)|Short title|"
    r"GOVERNMENT GAZETTE|Annotated Statutes|"
    r"CONSTITUTION OF|Republic of Namibia)"
)
ACT_URL_RE = re.compile(
    r"(?i)(/act[-_ ]|\bact[-_ ]|_act\.|-act\.|act\.pdf|constitution|"
    r"/bill[-_ ]|_bill\.|-bill\.|regulation|gazette|statutory|"
    r"acts_documents|cms_documents|promulgation)"
)

log = logging.getLogger("na")
HOMES = [
    # Live SSL flaky on many *.gov.na / parliament.gov.na; lean live set, lean on CDX/Wayback.
    "https://laws.parliament.na/",
    "https://laws.parliament.na/Bill-register",
    "https://www.parliament.na/",
    "https://www.parliament.na/bills/",
    "https://www.parliament.na/acts-of-parliament/",
]
ALLOWED = (
    "gov.na",
    "parliament.gov.na",
    "parliament.na",
    "laws.parliament.na",
)
DROP_RE = re.compile(
    r"(africanlii|namiblii|namlii|law\.africa|gazettes\.africa|"
    r"lac\.org\.na|saflii|commonlii|"
    r"/news/|/videos?/|interview|"
    r"facebook|youtube|twitter|logo|banner|photo|recruitment|vacancy|newsletter|"
    r"tender|procurement|job[_-]?announcement|press[_-]?release|"
    r"strategic.?plan|annual.?report|brochure|flyer|calendar|factsheet|"
    r"application.?form|speech|budget.?speech|manifesto|hansard|"
    r"speakercv|contribution|motivation|minutes|workshop)",
    re.I,
)
KEEP_RE = re.compile(
    r"(act|acts|bill|statute|ordinance|proclamation|gazette|law|legal|"
    r"constitution|subsidiary|instrument|regulation|order|cap\.?\s*\d|"
    r"amendment|decree|statutory.?instrument|\bSI\b|legislation|"
    r"acts_documents|cms_documents|promulgation)",
    re.I,
)
MAX_PDF_BYTES = 12 * 1024 * 1024


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(
        x in host
        for x in (
            "africanlii",
            "namiblii",
            "namlii",
            "gazettes.africa",
            "law.africa",
            "lac.org.na",
            "saflii",
            "commonlii",
        )
    ):
        return False
    for s in ALLOWED:
        if host == s or host.endswith("." + s):
            return True
    if host.endswith(".gov.na") or host == "gov.na":
        return True
    return False


def _norm_url(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    url = re.sub(r"(https?://[^/:]+):80/", r"\1/", url)
    url = re.sub(r"(https?://[^/:]+):80(/|$)", r"\1\2", url)
    return url


def prefer_enacting_body(text: str) -> str:
    """Skip arrangement/TOC so article split targets operative sections.

    Namibia often: BE IT ENACTED … then ARRANGEMENT OF SECTIONS (TOC), then body.
    Older gazettes wrap the enacting formula across lines.
    """
    if not text:
        return text

    arr = list(re.finditer(r"(?i)ARRANGEMENT OF (?:SECTIONS|ACT|REGULATIONS)", text))
    if arr:
        after = text[arr[-1].end() :]
        body_ones = list(
            re.finditer(
                r"(?im)^\s*(?:[A-Z][A-Za-z0-9 \-]{1,45}\.\s+)?"
                r"1\.\s+(?:In this Act|This Act|These Regulations|These regulations|"
                r"Unless the context|For the purposes|\(1\))",
                after,
            )
        )
        if body_ones:
            return after[body_ones[0].start() :]
        parts = list(re.finditer(r"(?im)^\s*PART\s+(?:1|I)\b", after))
        if len(parts) >= 2:
            return after[parts[1].start() :]
        ones = list(
            re.finditer(
                r"(?im)^\s*1\.\s+(?:Short title|Citation|Definitions|Interpretation)\b",
                after,
            )
        )
        if len(ones) >= 2:
            return after[ones[1].start() :]
        heads = list(
            re.finditer(
                r"(?im)^\s*(Definitions|Interpretation|Short title(?: and commencement)?)\s*$",
                after,
            )
        )
        if len(heads) >= 2:
            return after[heads[1].start() :]
        m = re.search(r"(?im)^\s*1\.\s+\(1\)", after)
        if m:
            return after[m.start() :]

    m = re.search(
        r"(?is)BE IT ENACTED\b.{0,160}?as follows\s*[:-]?",
        text,
    )
    if m and m.end() < len(text) - 200:
        rest = text[m.end() :]
        if not re.search(r"(?i)ARRANGEMENT OF", rest[:1500]):
            return rest

    body_ones = list(
        re.finditer(
            r"(?im)^\s*(?:[A-Z][A-Za-z0-9 \-]{1,45}\.\s+)?"
            r"1\.\s+(?:In this Act|This Act|These Regulations|These regulations)\b",
            text,
        )
    )
    if body_ones:
        return text[body_ones[-1].start() :] if len(body_ones) >= 2 else text[body_ones[0].start() :]

    ones = list(re.finditer(r"(?im)^\s*1\.\s+(?:Short title|Citation|Definitions)\b", text))
    if len(ones) >= 2:
        return text[ones[1].start() :]
    parts = list(re.finditer(r"(?im)^\s*PART\s+(?:1|I)\b", text))
    if len(parts) >= 2:
        return text[parts[1].start() :]
    return text


def split_na_articles(text: str, rid: str, source_url: str, date=None) -> list:
    """Commonwealth ``1. Title.`` body split by default; constitutions prefer Article N."""
    body = prefer_enacting_body(text)
    docs_sec = split_custom(body, rid, source_url, date, ART)
    docs_art = split_custom(body, rid, source_url, date, ART_ONLY)
    blob = f"{rid}|{source_url}"
    is_const = bool(re.search(r"(?i)constitution", blob)) and not bool(
        re.search(r"(?i)amm?endment", blob)
    )
    if is_const:
        if len(docs_art) >= 20:
            return docs_art
        if len(docs_art) >= 2 and len(docs_sec) > max(20, len(docs_art) * 3):
            return docs_art
        if len(docs_art) < 2:
            return docs_art
    if len(docs_art) >= 50 and len(docs_art) > len(docs_sec) * 1.2:
        return docs_art
    return docs_sec


def save_na_instrument(
    *,
    ident: str,
    title: str,
    text: str,
    source_url: str,
    extra_meta: dict | None = None,
) -> bool:
    if not text or len(text) < 80:
        return False
    rid = slug_id(CC, ident)
    docs = split_na_articles(text, rid, source_url, None)
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
        collector="collect_na.py",
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
        blob = f"{name}|{rec.get('title') or ''}|{rec.get('source_url') or ''}|{text[:2500]}"
        if not (ACT_TEXT_RE.search(blob) or ACT_URL_RE.search(blob)):
            continue
        rid = rec.get("id") or p.stem
        url = rec.get("source_url") or ""
        date = rec.get("date")
        docs = split_na_articles(text, rid, url, date)
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
        meta["article_reprocess"] = "collect_na.py-commonwealth-sections"
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


def discover():
    """Return list of (ident, url, wayback_ts|None). Live homes first; CDX with timestamps."""
    items = []  # (priority, ident, url, ts)
    seen = set()

    def add(url: str, ts: str | None = None, priority: int = 50):
        url = _norm_url(url)
        if not url.startswith("http"):
            return
        if not _host_ok(url) or DROP_RE.search(url):
            return
        if ".pdf" not in url.lower():
            return
        blob = unquote(url)
        if not KEEP_RE.search(blob):
            if not re.search(
                r"(?i)/(acts?|laws?|gazette|legislation|publications?|documents?|"
                r"downloads?|files?|statutory|si[_/\-]|cap[_/\-]|"
                r"acts_documents|cms_documents|uploads)",
                blob,
            ):
                return
        key = url.lower()
        if key in seen:
            return
        seen.add(key)
        ident = re.sub(r"^https?://[^/]+/", "", unquote(url)).replace("/", "-").replace("?", "-")[:160]
        items.append((priority, ident, url, ts))

    for home in HOMES:
        try:
            r = http_get(home, ua=UA, sleep=0.25)
            if getattr(r, "status_code", 0) != 200:
                continue
            for href in re.findall(r'href=["\']([^"\']+)["\']', r.text or "", re.I):
                add(urljoin(home, href.replace("&amp;", "&")), ts=None, priority=10)
            for href in re.findall(r'(https?://[^\s"\'<>]+\.pdf)', r.text or "", re.I):
                add(href, ts=None, priority=10)
            for href in re.findall(r'["\'](/[^"\']+\.pdf)["\']', r.text or "", re.I):
                add(urljoin(home, href), ts=None, priority=10)
        except Exception as exc:
            log.info("home %s %s", home, exc)

    cdx_prefixes = (
        "www.parliament.gov.na/acts_documents/",
        "parliament.gov.na/acts_documents/",
        "www.parliament.gov.na/bills_documents/",
        "parliament.gov.na/bills_documents/",
        "www.parliament.gov.na/",
        "parliament.gov.na/",
        "laws.parliament.na/cms_documents/",
        "laws.parliament.na/",
        "www.parliament.na/wp-content/uploads/",
        "parliament.na/wp-content/uploads/",
        "www.parliament.na/",
        "www.gov.na/documents/",
        "gov.na/documents/",
        "www.moj.gov.na/",
        "moj.gov.na/",
        "www.opm.gov.na/",
        "opm.gov.na/",
        "www.mof.gov.na/",
        "www.mti.gov.na/",
        "www.mhss.gov.na/",
        "www.npc.gov.na/",
        "www.lac.gov.na/",  # only if *.gov.na — lac.org.na blocked by host check
    )
    for prefix in cdx_prefixes:
        try:
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 280),
                match_type="prefix",
                extra_filters=["statuscode:200", "mimetype:application/pdf"],
            ) or []
        except Exception as exc:
            log.info("cdx %s %s", prefix, exc)
            hits = []
        for h in hits:
            orig = h.get("original") or ""
            ts = (h.get("timestamp") or "")[:14] or None
            try:
                length = int(h.get("length") or 0)
            except Exception:
                length = 0
            if length and length > MAX_PDF_BYTES:
                continue
            pri = 20
            blob = unquote(orig)
            if re.search(r"(?i)acts_documents|/_?act[_-]?\d|act_\d+_of_\d{4}|constitution", blob):
                pri = 5
            elif re.search(r"(?i)(bill|gazette|statutory|/laws?/|/legislation)", blob):
                pri = 12
            elif re.search(r"(?i)cms_documents", blob):
                # Prefer post-independence / Act-labelled CMS; bury colonial-era noise
                if re.search(r"(?i)(act|amendment|constitution|proclamation)", blob) and not re.search(
                    r"(?i)(15[0-9]{2}|16[0-9]{2}|17[0-9]{2}|18[0-9]{2}|19[0-5][0-9])", blob
                ):
                    pri = 14
                else:
                    pri = 35
            elif re.search(r"(?i)(act|regulation)", blob):
                pri = 18
            add(orig, ts=ts, priority=pri)

    items.sort(key=lambda x: (x[0], x[1]))
    out = [(ident, url, ts) for _, ident, url, ts in items]
    log.info("catalog %s", len(out))
    return out


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 2400)
    do_reprocess = os.environ.get("REPROCESS", "1") not in ("0", "false", "no")

    if do_reprocess:
        n = reprocess_existing()
        log.info("reprocess improved=%s", n)

    t_start = time.time()
    done = existing_ids(CC)
    already = len(done)
    target_total = env_int("TARGET_TOTAL", 0)
    have_urls = set()
    for p in (ROOT / CC / "instruments").glob("*.json"):
        try:
            u = _norm_url(json.loads(p.read_text(encoding="utf-8")).get("source_url") or "")
            if u:
                have_urls.add(u.lower())
        except Exception:
            pass

    ok = skip = fail = 0
    for ident, url, ts in discover():
        if max_new and ok >= max_new:
            break
        if target_total and (already + ok) >= target_total:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        nu = _norm_url(url).lower()
        if rid in done or nu in have_urls:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, min_text=200, wayback_ts=ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error"), "wayback_ts": ts})
            continue
        if len(text) > 2_500_000:
            log.info("skip huge text chars=%s %s", len(text), ident[:50])
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_too_large", "chars": len(text)})
            continue
        title = first_title(text, ident)
        blob = f"{ident}|{title}|{url}|{text[:2500]}"
        # Prefer Act-ish PDFs; skip obvious non-law once we have a base set
        if ok >= 10 and not ACT_TEXT_RE.search(blob) and not ACT_URL_RE.search(url):
            if not re.search(r"(?i)\b(ACT|BILL|STATUTE|ORDINANCE|CONSTITUTION|GAZETTE|REGULATION)\b", text[:3000]):
                skip += 1
                log.info("skip non-act post-fetch %s", ident[:60])
                continue
        if save_na_instrument(
            ident=ident,
            title=title,
            text=text,
            source_url=_norm_url(url),
            extra_meta={"fetch_method": got.get("method"), "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            have_urls.add(nu)
            log.info("ok %s method=%s chars=%s ts=%s", ident[:60], got.get("method"), len(text), ts)
        else:
            fail += 1

    rebuild_index()
    arts = 0
    n_inst = 0
    for p in (ROOT / CC / "instruments").glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        n_inst += 1
        arts += int(rec.get("article_count") or len(rec.get("documents") or []) or 0)

    write_summary(
        CC,
        country=COUNTRY,
        source="Namibia Official Gazette / Acts (parliament.gov.na / laws.parliament.na / gov.na / moj.gov.na / opm.gov.na)",
        source_urls=[
            "https://www.parliament.gov.na/",
            "https://laws.parliament.na/",
            "https://www.parliament.na/",
            "https://www.gov.na/",
            "https://www.moj.gov.na/",
            "https://www.opm.gov.na/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete (PDF-first live+CDX *.gov.na / parliament.na; commonwealth section densify)",
        notes=(
            f"Official *.gov.na / parliament.na PDFs only. Commonwealth 1. section split + "
            f"enacting-body prefer. instruments={n_inst} articles={arts}. "
            f"Not AfricanLII/NamibLII/lac.org.na. No WAF bypass. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s instruments=%s articles=%s", ok, skip, fail, n_inst, arts)


if __name__ == "__main__":
    main()
