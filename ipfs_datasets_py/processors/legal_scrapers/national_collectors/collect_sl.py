#!/usr/bin/env python3
"""Sierra Leone (sl): official Acts / gazettes PDFs via *.gov.sl.

Official only:
  - parliament.gov.sl (Acts / Bills / uploads)
  - judiciary.gov.sl
  - moj.gov.sl / attorneygeneral.gov.sl (AG & Ministry of Justice)
  - statehouse.gov.sl / cabinet.gov.sl / gov.sl / mof.gov.sl gazette hosts
  - Wayback/CDX of the same official *.gov.sl URLs

Live SSL on many *.gov.sl hosts is flaky from collector egress — CDX/Wayback primary;
short live probes with verify=False. NOT SierraLII (sierralii.gov.sl) / AfricanLII.
No WAF bypass. Skip PDFs >12MB. Not legal advice.

Densify: Sierra Leone Acts use Commonwealth ``1. Short title.`` / ``1. Interpretation``
section numbering (not only ``Section N`` / ``Part N``). Prefer enacting body after
BE IT ENACTED / ARRANGEMENT OF SECTIONS / second ``1.`` to avoid TOC double-count.
OCR often drops the space after the section number (``1.In this Act``).
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

CC, COUNTRY, LANG = "sl", "Sierra Leone", "en"
SOURCE_TYPE = "sierra_leone_official_gazette_acts"
LICENSE = (
    "Republic of Sierra Leone — Parliament (parliament.gov.sl) / "
    "Judiciary (judiciary.gov.sl) / Attorney General & Ministry of Justice "
    "(moj.gov.sl / attorneygeneral.gov.sl) / State House / Cabinet / other *.gov.sl "
    "gazette hosts. Authentic Official Gazette / Act text prevails. "
    "Not SierraLII as LII source text. Not AfricanLII. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.parliament.gov.sl/)"

# Commonwealth body: "1. Short title." / "12A. Interpretation." / "1.In this Act"
# PLUS classic Section/Article/Part/Chapter N
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|Cap\.?|Chapter|Part)\s*[0-9]+[A-Za-z]?|"
    r"\d+[A-Za-z]?\.)(?=\s*(?:[A-Z\"'(]|In |This |These |The |For ))"
)
ART_ONLY = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+[A-Za-z]?)\b")

ACT_TEXT_RE = re.compile(
    r"(?i)(?:BE IT ENACTED|ARRANGEMENT OF SECTIONS|STATUTORY INSTRUMENTS?|"
    r"SUPPLEMENT (?:to the Sierra Leone Gazette|No\.)|Act No\.|"
    r"This Act may be cited|Short title|Passed in Parliament|"
    r"I assent|Date of commencement|AN ACT\b|A BILL\b|"
    r"THE\s+[A-Z][A-Z0-9 \-',()]{6,90}\s+ACT,?\s*\d{4})"
)
ACT_URL_RE = re.compile(
    r"(?i)(?:/uploads/acts|bill_files|_act\.pdf|act\.pdf|act%20|"
    r"constitution|statutory|gazette|fileticket|/acts?/)"
)
JUNK_RE = re.compile(
    r"(?i)reoi|cartoon|expression.?of.?interest|consultant|"
    r"terms.?of.?reference|\btor\b|vacancy|strategic.?plan|annual.?report|"
    r"Project Development Objective|QCBS|BADEA|RUSLP|"
    r"procurement.?plan|code.?of.?practice|simplified-pfm|"
    r"enacted.?budget|audit.?recommendations|uhc.?in.?sierra|"
    r"confirmed.?cases.?of.?ebola|press.?release"
)

log = logging.getLogger("sl")

# Lean live set — SSL often EOF; CDX+seeds primary
HOMES = [
    "https://www.parliament.gov.sl/",
    "https://www.parliament.gov.sl/acts",
    "https://www.parliament.gov.sl/bills",
]

ALLOWED = ("gov.sl",)
DROP_RE = re.compile(
    r"(sierralii|africanlii|law\.africa|gazettes\.africa|"
    r"/news/|/videos?/|interview|facebook|youtube|twitter|logo|banner|photo|"
    r"recruitment|vacancy|newsletter|tender|procurement|job[_-]?announcement|"
    r"press[_-]?release|strategic.?plan|annual.?report|brochure|flyer|calendar|"
    r"factsheet|application.?form|speech|budget.?speech|manifesto|cv[-_]|"
    r"biograph|organigram|presentation|cassette|petty.?traders|restaurant|"
    r"workshop|seminar|powerpoint|\bppt\b|reoi|cartoon|expression.?of.?interest)",
    re.I,
)
KEEP_RE = re.compile(
    r"(act|acts|bill|statute|ordinance|proclamation|gazette|law|legal|"
    r"constitution|subsidiary|instrument|regulation|order|cap\.?\s*\d|"
    r"amendment|decree|statutory.?instrument|\bSI\b|legislation|"
    r"uploads/(acts|bill))",
    re.I,
)
MAX_PDF_BYTES = 12 * 1024 * 1024

SEED_PDFS = [
    "https://www.parliament.gov.sl/uploads/acts/THE%20FINANCE%20ACT%202022.pdf",
    "https://www.parliament.gov.sl/uploads/bill_files/The%20Criminal%20Procedure%20Act,%202024.pdf",
    "https://www.parliament.gov.sl/uploads/acts/THE%20FINANCE%20ACT,%202021.pdf",
    "https://www.parliament.gov.sl/uploads/acts/THE%20APPROPRIATION%20ACT,%202021.pdf",
    "https://www.parliament.gov.sl/uploads/acts/THE%20FINANCE%20ACT,%202020.pdf",
    "https://www.parliament.gov.sl/uploads/acts/THE%20FINANCE%20ACT,%202019.pdf",
    "https://www.parliament.gov.sl/uploads/acts/THE%20FINANCE%20ACT,%202018.pdf",
    "https://www.parliament.gov.sl/uploads/acts/THE%20PUBLIC%20FINANCIAL%20MANAGEMENT%20ACT,%202016.pdf",
    "https://www.parliament.gov.sl/uploads/acts/THE%20NATIONAL%20MINERALS%20AGENCY%20ACT,%202012.pdf",
    "https://www.parliament.gov.sl/uploads/acts/THE%20GOODS%20AND%20SERVICES%20TAX%20ACT,%202009.pdf",
]

CDX_PREFIXES = (
    "www.parliament.gov.sl/uploads/acts/",
    "parliament.gov.sl/uploads/acts/",
    "www.parliament.gov.sl/uploads/bill_files/",
    "parliament.gov.sl/uploads/bill_files/",
    "www.parliament.gov.sl/uploads/",
    "parliament.gov.sl/uploads/",
    "www.parliament.gov.sl/",
    "parliament.gov.sl/",
    "publications.parliament.gov.sl/",
    "www.judiciary.gov.sl/",
    "judiciary.gov.sl/",
    "www.moj.gov.sl/",
    "moj.gov.sl/",
    "www.attorneygeneral.gov.sl/",
    "attorneygeneral.gov.sl/",
    "www.statehouse.gov.sl/",
    "statehouse.gov.sl/",
    "www.cabinet.gov.sl/",
    "cabinet.gov.sl/",
    "www.gov.sl/",
    "gov.sl/",
    "www.mof.gov.sl/",
    "mof.gov.sl/",
    "www.nra.gov.sl/",
    "nra.gov.sl/",
    "www.lawreform.gov.sl/",
    "lawreform.gov.sl/",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(x in host for x in ("sierralii", "africanlii", "gazettes.africa", "law.africa")):
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED)


def _norm_url(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return ""
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    url = re.sub(r"(https?://[^/:]+):80/", r"\1/", url)
    url = re.sub(r"(https?://[^/:]+):80(/|$)", r"\1\2", url)
    return url


def prefer_enacting_body(text: str) -> str:
    """Skip arrangement/TOC so article split targets operative sections.

    SL OCR often writes ``1.In this Act`` (no space). Prefer that body cue over
    TOC ``1. Interpretation`` lines.
    """
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
            r"(?im)^\s*1\.\s*(?:Short title|Citation|Interpretation|Definitions)\b",
            text,
        )
    )
    if len(ones) >= 2:
        return text[ones[1].start() :]
    if len(ones) == 1:
        arr = re.search(r"(?i)ARRANGEMENT OF", text)
        if arr and ones[0].start() > arr.start():
            return text[ones[0].start() :]

    m = re.search(r"(?i)ARRANGEMENT OF (?:SECTIONS|RULES|ORDERS)", text)
    if m:
        after = text[m.end() :]
        body = list(
            re.finditer(
                r"(?im)^\s*1\.\s*(?:Short title|Citation|Interpretation|Definitions|"
                r"This Act|In this Act)\b",
                after,
            )
        )
        if body:
            return after[body[-1].start() :] if len(body) >= 2 else after[body[0].start() :]
        parts = list(re.finditer(r"(?im)^\s*PART\s+I\b", after))
        if len(parts) >= 2:
            return after[parts[1].start() :]
    return text


def split_sl_articles(text: str, rid: str, source_url: str, date=None) -> list:
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


def save_sl_instrument(
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
    docs = split_sl_articles(text, rid, source_url, None)
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
        collector="collect_sl.py",
        documents=docs,
        extra_meta=meta,
    )
    write_instrument(CC, rec)
    return True


def _is_act_like(rec: dict, name: str) -> bool:
    text = rec.get("text") or ""
    blob = f"{name}|{rec.get('title') or ''}|{rec.get('source_url') or ''}|{text[:3000]}"
    if text[:2000].count("HON.") >= 8:
        return False
    if JUNK_RE.search(blob) and not ACT_TEXT_RE.search(blob):
        return False
    return bool(ACT_TEXT_RE.search(blob) or (ACT_URL_RE.search(blob) and ACT_TEXT_RE.search(text[:8000])))


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
        if not _is_act_like(rec, p.name):
            continue
        rid = rec.get("id") or p.stem
        url = rec.get("source_url") or ""
        date = rec.get("date")
        docs = split_sl_articles(text, rid, url, date)
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
        meta["article_reprocess"] = "collect_sl.py-commonwealth-sections"
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
    """Return list of (ident, url, wayback_ts|None). CDX-primary; short live probes."""
    items = []  # (priority, ident, url, ts)
    seen = set()

    def add(url: str, ts: str | None = None, priority: int = 50, from_cdx_pdf: bool = False):
        url = _norm_url(url)
        if not url.startswith("http"):
            return
        if not _host_ok(url) or DROP_RE.search(url):
            return
        low = url.lower()
        blob = unquote(url)
        is_pdf_ext = ".pdf" in low
        is_doc_dl = bool(
            re.search(r"(?i)(linkclick\.aspx|fileticket=|/download|/file\.aspx|/getfile)", low)
        )
        if not is_pdf_ext and not (from_cdx_pdf and is_doc_dl):
            return
        if not is_pdf_ext and from_cdx_pdf and is_doc_dl:
            pass
        elif not KEEP_RE.search(blob):
            if not re.search(
                r"(?i)/(acts?|laws?|gazette|legislation|publications?|documents?|"
                r"downloads?|files?|uploads?|bill_files|statutory|si[_/\-]|cap[_/\-])",
                blob,
            ):
                return
        key = url.lower()
        if key in seen:
            return
        seen.add(key)
        m = re.search(r"(?i)fileticket=([^&]+)", url)
        if m:
            ident = "parliament-fileticket-" + re.sub(r"\W+", "", unquote(m.group(1)))[:48]
        else:
            ident = (
                re.sub(r"^https?://[^/]+/", "", unquote(url))
                .replace("/", "-")
                .replace("?", "-")[:160]
            )
        items.append((priority, ident, url, ts))

    for seed in SEED_PDFS:
        add(seed, ts=None, priority=5)

    for home in HOMES:
        try:
            r = live_get(home, ua=UA, verify=False, timeout=(8, 20), retries=1)
            if getattr(r, "status_code", 0) != 200:
                log.info("home %s status=%s", home, getattr(r, "status_code", None))
                continue
            for href in re.findall(r'href=["\']([^"\']+)["\']', r.text or "", re.I):
                add(urljoin(home, href.replace("&amp;", "&")), ts=None, priority=10)
            for href in re.findall(r'(https?://[^\s"\'<>]+\.pdf)', r.text or "", re.I):
                add(href, ts=None, priority=10)
        except Exception as exc:
            log.info("home %s %s", home, exc)

    for prefix in CDX_PREFIXES:
        try:
            hits = (
                cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 300),
                    match_type="prefix",
                    extra_filters=["statuscode:200", "mimetype:application/pdf"],
                )
                or []
            )
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
            if re.search(
                r"(?i)(act|gazette|constitution|statutory|/laws?/|/legislation|bill)",
                unquote(orig),
            ):
                pri = 15
            if re.search(r"(?i)/uploads/acts/|bill_files", unquote(orig)):
                pri = 8
            add(orig, ts=ts, priority=pri, from_cdx_pdf=True)

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
        got = fetch_official(url, ua=UA, min_text=200, wayback_ts=ts, verify=False)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": ident,
                    "source_url": url,
                    "reason": got.get("error"),
                    "wayback_ts": ts,
                },
            )
            continue
        if len(text) > 2_500_000:
            log.info("skip huge text chars=%s %s", len(text), ident[:50])
            fail += 1
            log_failure(
                CC,
                {
                    "identifier": ident,
                    "source_url": url,
                    "reason": "text_too_large",
                    "chars": len(text),
                },
            )
            continue
        title = first_title(text, ident)
        blob = f"{ident}|{title}|{url}|{text[:2500]}"
        if JUNK_RE.search(blob) and not ACT_TEXT_RE.search(blob):
            skip += 1
            log.info("skip junk post-fetch %s", ident[:60])
            continue
        if text[:2000].count("HON.") >= 8 and not ACT_TEXT_RE.search(blob):
            skip += 1
            log.info("skip mp-list post-fetch %s", ident[:60])
            continue
        if save_sl_instrument(
            ident=ident,
            title=title,
            text=text,
            source_url=_norm_url(url),
            extra_meta={"fetch_method": got.get("method"), "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            have_urls.add(nu)
            log.info(
                "ok %s method=%s chars=%s ts=%s",
                ident[:60],
                got.get("method"),
                len(text),
                ts,
            )
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
        source=(
            "Sierra Leone Official Gazette / Acts "
            "(parliament.gov.sl / judiciary.gov.sl / moj.gov.sl / attorneygeneral.gov.sl)"
        ),
        source_urls=[
            "https://www.parliament.gov.sl/",
            "https://www.judiciary.gov.sl/",
            "https://www.moj.gov.sl/",
            "https://www.attorneygeneral.gov.sl/",
            "https://www.statehouse.gov.sl/",
            "https://www.gov.sl/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (PDF-first CDX *.gov.sl + short live probes; "
            "commonwealth section densify)"
        ),
        notes=(
            f"Official *.gov.sl PDFs only. Commonwealth 1. Section split + enacting-body prefer. "
            f"instruments={n_inst} articles={arts}. Not SierraLII/AfricanLII as source text. "
            f"No WAF bypass. Not legal advice."
        ),
        last_run=t0,
    )
    log.info(
        "done ok=%s skip=%s fail=%s total_instruments=%s articles=%s",
        ok,
        skip,
        fail,
        n_inst,
        arts,
    )


if __name__ == "__main__":
    main()
