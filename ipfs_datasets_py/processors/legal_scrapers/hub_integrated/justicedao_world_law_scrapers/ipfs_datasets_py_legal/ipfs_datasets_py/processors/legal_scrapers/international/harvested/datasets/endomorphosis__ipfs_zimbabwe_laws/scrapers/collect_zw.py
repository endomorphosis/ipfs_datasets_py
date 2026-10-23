#!/usr/bin/env python3
"""Zimbabwe: official Acts / gazettes via CDX/Wayback of *.gov.zw URLs.

Official *.gov.zw only. Live hosts often SSL/DNS-fail — prefer Wayback of official
CDX URLs (parlzim.gov.zw acts-list/download + wp-content Acts; justice/zim).
Veritas (veritaszim.net) is NOT official — excluded.
Not AfricanLII / ZimbabweLII / commercial DBs. No WAF bypass.

Densify: Zimbabwe Acts use Commonwealth ``1. Short title.`` section numbering (not only
``Section N`` / ``Article N``). Prefer enacting body after ``BE IT ENACTED`` / TOC
(port of ug/mu/tz/gh/zm).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_fallbacks as af
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
    pdf_to_text,
    setup_log,
    slug_id,
    split_custom,
)

CC, COUNTRY, LANG = "zw", "Zimbabwe", "en"
SOURCE_TYPE = "zimbabwe_official_gazette_acts"
LICENSE = (
    "Republic of Zimbabwe — Parliament (parlzim.gov.zw / parliament.gov.zw) / Ministry of Justice "
    "(justice.gov.zw) / Government Portal (zim.gov.zw) / OPC (opc.gov.zw) / Treasury "
    "(zimtreasury.gov.zw) and other *.gov.zw hosts. Authentic Official Gazette / Act text prevails. "
    "Not Veritas / AfricanLII / ZimbabweLII / commercial DBs. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.parlzim.gov.zw/)"

# Commonwealth body: "1. Short title." / "12A. Interpretation." PLUS classic Section/Article
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?)\s+[0-9]+[A-Za-z]?|"
    r"\d+[A-Za-z]?\.)(?=\s+[A-Z\"'(])"
)
ART_ONLY = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+[A-Za-z]?)\b")

ACT_TEXT_RE = re.compile(
    r"(?i)(?:BE IT ENACTED|ARRANGEMENT OF SECTIONS|AN ACT\b|A BILL\b|"
    r"This Act may be cited|Short title|I assent|Date of commencement|"
    r"STATUTORY INSTRUMENT|S\.I\.\s*\d|GOVERNMENT GAZETTE|"
    r"CHAPTER\s+\d+|Cap\.\s*\d+|CONSTITUTION|"
    r"PARLIAMENT OF ZIMBABWE|REPUBLIC OF ZIMBABWE|"
    r"THE\s+[A-Z][A-Z0-9 \-',()]{6,100}\s+ACT\b)"
)
ACT_URL_RE = re.compile(
    r"(?i)(?:/acts?/|_act\.|-act\.|act\.pdf|/laws?/|constitution|"
    r"acts-list/download|statutory|gazette|legislation|"
    r"amendment|education.?act|labour.?act|finance.?act)"
)
JUNK_RE = re.compile(
    r"(?i)imt.?discussion|laymans.?draft|nr.?scw.?report|sr.?scw.?report|"
    r"discussion.?paper|bill.?digest|analysis.?of|stakeholder.?consult|"
    r"annual.?report|strategic.?plan|press.?release|newsletter|vacancy|"
    r"tender|procurement|brochure|flyer|calendar|speech|manifesto|"
    r"budget.?speech|budget.?highlights|service.?charter|zim.?asset"
)

log = logging.getLogger("zw")
ALLOWED = ("gov.zw",)
DROP_RE = re.compile(
    r"(veritaszim|veritas\.|africanlii|zimbabwelii|zimlii|law\.africa|gazettes\.africa|"
    r"/news/|/videos?/|interview|facebook|youtube|twitter|logo|banner|photo|"
    r"recruitment|vacancy|newsletter|tender|procurement|job[_-]?announcement|"
    r"press[_-]?release|strategic.?plan|annual.?report|brochure|flyer|calendar|"
    r"factsheet|application.?form|speech|budget.?speech|manifesto|lawsoc|"
    r"hansard|votes.?and.?proceedings|budget.?outturn|budget.?policy|"
    r"estimates.?of.?expenditure|consolidated.?fin|imf.?staff|"
    r"national.?budget.?highlights|economic.?brief|budget.?office|"
    r"public.?hearing|guidelines?|roles.?functions|history.?of.?women|"
    r"leader.?of.?gover|command.?agriculture|retention.?funds|"
    r"seacmeq|contract\.pdf|ipc.?training|cholera.?update|service.?charter|"
    r"nutrition|memorandum.?to.?cabinet|national.?health.?strategy|"
    r"imt.?discussion|laymans.?draft|nr.?scw.?report|sr.?scw.?report|"
    r"discussion.?paper|bill.?digest|analysis.?of)",
    re.I,
)
KEEP_RE = re.compile(
    r"(act|acts|bill|statute|ordinance|proclamation|gazette|law|legal|"
    r"constitution|subsidiary|instrument|regulation|order|cap\.?\s*\d|"
    r"amendment|decree|statutory.?instrument|\bSI\b|legislation|"
    r"acts-list/download)",
    re.I,
)
MAX_PDF_BYTES = 8 * 1024 * 1024
CDX_PDF_PATH_RE = re.compile(r"(?i)acts-list/download/\d+|finance-act\?download=")

# Known good official PDFs (CDX timestamps) — Wayback-first seeds
SEED = [
    (
        "https://www.parlzim.gov.zw/wp-content/uploads/2025/05/Constitution-of-Zimbabwe-Amendment_No_20_-_14-05-2013.pdf",
        None,
        5,
    ),
    (
        "https://parlzim.gov.zw/wp-content/uploads/2021/07/Constitution-of-Zimbabwe-Amendment_No_20_-_14-05-2013.pdf",
        "20210715000000",
        5,
    ),
    (
        "https://www.mopse.gov.zw/wp-content/uploads/2024/07/EDUCATION-ACT.pdf",
        None,
        8,
    ),
]


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(x in host for x in (
        "veritaszim", "africanlii", "zimbabwelii", "zimlii",
        "gazettes.africa", "law.africa", "lawsoc",
    )):
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED)


def _norm_url(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    url = re.sub(r"(https?://[^/:]+):80/", r"\1/", url)
    url = url.replace("\\", "/")
    return url


def _is_pdf_candidate(url: str, from_cdx_pdf: bool = False) -> bool:
    u = url.lower()
    if ".pdf" in u:
        return True
    if from_cdx_pdf and CDX_PDF_PATH_RE.search(u):
        return True
    return False


def _title_from_text(text: str, fallback: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in lines[:40]:
        if re.search(r"(?i)constitution\s+of\s+zimbabwe", ln) and len(ln) > 20:
            return ln[:240]
    for i, ln in enumerate(lines[:60]):
        if re.search(r"(?i)\bACT\b", ln) and len(ln) >= 10 and not re.match(r"(?i)^(title|chapter|acts?\s+\d)", ln):
            if re.search(r"[A-Za-z]{3,}", ln):
                chap = None
                for j in range(max(0, i - 3), i):
                    if re.match(r"(?i)^chapter\s+\d+", lines[j]):
                        chap = lines[j]
                        break
                title = f"{chap} — {ln}" if chap else ln
                return title[:240]
    for ln in lines:
        if len(ln) > 18 and not re.match(r"(?i)^title\s+\d+$", ln):
            return ln[:240]
    return fallback[:240]


def prefer_enacting_body(text: str) -> str:
    """Skip arrangement/TOC so article split targets operative sections.

    Multi-Act Cap volumes (many ``1. Short title``) must NOT truncate to the last Act
    via body_ones[-1]; densify the whole volume from the first enacting body onward.
    """
    if not text:
        return text

    short_ones = list(
        re.finditer(
            r"(?im)^\s*1\.\s+(?:Short title|Citation|Interpretation|Definitions)\b",
            text,
        )
    )
    multi_act = len(short_ones) >= 3

    m = re.search(r"(?is)BE IT ENACTED[^\n]*\n", text)
    if m and m.end() < len(text) - 200:
        rest = text[m.end() :]
        arr = re.search(r"(?i)ARRANGEMENT OF (?:SECTIONS|RULES|ORDERS)", rest[:2500])
        if not arr:
            if not multi_act:
                return rest
            if len(rest) > len(text) * 0.5:
                text = rest

    if not multi_act:
        body_ones = list(
            re.finditer(
                r"(?im)^\s*1\.\s*(?:This Act|In this Act|These Regulations|These regulations|"
                r"Unless the context|For the purposes)\b",
                text,
            )
        )
        if body_ones:
            return text[body_ones[0].start() :]

    if len(short_ones) >= 2:
        # second Short title ≈ first Act body (first is usually TOC)
        return text[short_ones[1].start() :]
    if len(short_ones) == 1:
        arr = re.search(r"(?i)ARRANGEMENT OF", text)
        if arr and short_ones[0].start() > arr.start():
            return text[short_ones[0].start() :]

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
        if multi_act and body:
            return after[body[0].start() :]
        if len(body) >= 2:
            return after[body[1].start() :]
        parts = list(re.finditer(r"(?im)^\s*PART\s+I\b", after))
        if len(parts) >= 2:
            return after[parts[1].start() :]
        if body:
            return after[body[0].start() :]
    return text


def split_zw_articles(text: str, rid: str, source_url: str, date=None) -> list:
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
            return docs_sec if docs_sec else docs_art
    if len(docs_art) >= 50 and len(docs_art) > len(docs_sec) * 1.2:
        return docs_art
    return docs_sec


def save_zw_instrument(
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
    docs = split_zw_articles(text, rid, source_url, date)
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
        collector="collect_zw.py",
        date=date,
        documents=docs,
        extra_meta=meta,
    )
    write_instrument(CC, rec)
    return True


def _is_junk_record(rec: dict, name: str) -> bool:
    blob = f"{name}|{rec.get('title') or ''}|{rec.get('source_url') or ''}"
    if JUNK_RE.search(blob) and not ACT_URL_RE.search(blob):
        text_head = (rec.get("text") or "")[:2500]
        if not ACT_TEXT_RE.search(text_head):
            return True
    return False


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
        if _is_junk_record(rec, name):
            continue
        blob = f"{name}|{rec.get('title') or ''}|{rec.get('source_url') or ''}|{text[:2500]}"
        if not (ACT_TEXT_RE.search(blob) or ACT_URL_RE.search(blob)):
            continue
        rid = rec.get("id") or p.stem
        url = rec.get("source_url") or ""
        date = rec.get("date")
        docs = split_zw_articles(text, rid, url, date)
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
        meta["article_reprocess"] = "collect_zw.py-commonwealth-sections"
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
    return len(rows)


def _wayback_fetch(url: str, ts: str | None) -> dict:
    """Wayback-only fetch of an official *.gov.zw URL (skip live SSL/DNS failures)."""
    out = {
        "status": "error", "text": "", "content": b"", "source_url": url,
        "method": "", "content_type": "", "error": "",
    }
    candidates = [url]
    if url.startswith("https://"):
        candidates.append("http://" + url[len("https://"):])
    last_err = ""
    for cand in candidates:
        try:
            w = af.get_wayback_content(cand, timestamp=ts)
        except Exception as exc:
            last_err = str(exc)
            continue
        if w.get("status") != "success":
            last_err = str(w.get("error") or "wayback_fail")
            continue
        raw_b = w.get("content") or b""
        raw_t = w.get("text") or ""
        pdf_bytes = None
        if isinstance(raw_b, bytes) and raw_b[:4] == b"%PDF":
            pdf_bytes = raw_b
        elif isinstance(raw_t, str) and raw_t[:4] == "%PDF":
            pdf_bytes = raw_t.encode("latin-1", "replace")
        if pdf_bytes:
            if len(pdf_bytes) > MAX_PDF_BYTES:
                out["error"] = "pdf_too_large"
                continue
            text = pdf_to_text(pdf_bytes)
            if len(text) >= 200 and not text.lstrip().startswith("%PDF"):
                out.update(
                    status="success", text=text, content=pdf_bytes,
                    method="wayback_pdf",
                    source_url=w.get("wayback_url") or w.get("url") or cand,
                    content_type="application/pdf",
                )
                return out
            out["error"] = "pdf_extract_failed"
            continue
        text = raw_t
        if len(text) >= 200:
            out.update(
                status="success", text=text, content=raw_b if isinstance(raw_b, bytes) else text.encode(),
                method="wayback_html",
                source_url=w.get("url") or cand,
                content_type=w.get("content_type") or "text/html",
            )
            return out
        last_err = "wayback_short"
    out["error"] = last_err or "wayback_fail"
    return out


def discover():
    """CDX-first discovery of official *.gov.zw Act PDFs (no live home crawl)."""
    items = []  # (priority, ident, url, ts)
    seen = set()

    def add(url: str, ts: str | None = None, priority: int = 50, from_cdx_pdf: bool = False):
        raw = (url or "").split("#")[0].strip()
        url_n = _norm_url(raw)
        if not url_n.startswith("http"):
            return
        if not _host_ok(url_n) or DROP_RE.search(url_n):
            return
        if not _is_pdf_candidate(url_n, from_cdx_pdf=from_cdx_pdf):
            return
        blob = unquote(url_n)
        if not KEEP_RE.search(blob):
            if not re.search(
                r"(?i)/(acts?|laws?|gazette|legislation|publications?|documents?|"
                r"downloads?|files?|statutory|si[_/\-]|cap[_/\-]|wp-content/uploads)",
                blob,
            ):
                return
        key = re.sub(r"^https?://(www\.)?", "", url_n.lower())
        key = re.sub(r"/+", "/", key)
        if "download=" not in key:
            key = key.split("?")[0]
        m = re.search(r"acts-list/download/(\d+_[a-f0-9]+)", key)
        if m:
            key = "parlzim-download-" + m.group(1)
        if key in seen:
            return
        seen.add(key)
        ident = re.sub(r"^https?://[^/]+/", "", unquote(url_n)).replace("/", "-").replace("?", "-").replace("\\", "-")[:160]
        fetch_url = raw if raw.startswith("http") else url_n
        items.append((priority, ident, fetch_url, ts))

    for url, ts, pri in SEED:
        add(url, ts=ts, priority=pri)

    cdx_prefixes = (
        "www.parlzim.gov.zw/acts-list/download/",
        "parlzim.gov.zw/acts-list/download/",
        "www.parlzim.gov.zw/wp-content/uploads/",
        "parlzim.gov.zw/wp-content/uploads/",
        "www.parlzim.gov.zw/cms/Acts/",
        "parlzim.gov.zw/cms/Acts/",
        "www.justice.gov.zw/imt/wp-content/uploads/",
        "www.justice.gov.zw/",
        "justice.gov.zw/",
        "www.zim.gov.zw/sites/default/files/",
        "zim.gov.zw/sites/default/files/",
        "www.mopse.gov.zw/wp-content/uploads/",
        "mopse.gov.zw/wp-content/uploads/",
        "www.zimtreasury.gov.zw/finance-act",
    )
    for prefix in cdx_prefixes:
        try:
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 220),
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
            if length and length < 15000:
                continue
            blob = unquote(orig)
            pri = 25
            if re.search(r"(?i)constitution", blob):
                pri = 6
            elif re.search(r"(?i)(_ACT_|/Acts/|ACT\.pdf|acts-list/download)", blob):
                pri = 12
            elif re.search(r"(?i)(act|gazette|statutory|/laws?/|/legislation)", blob):
                pri = 18
            add(orig, ts=ts, priority=pri, from_cdx_pdf=True)

    items.sort(key=lambda x: (x[0], x[1]))
    out = [(ident, url, ts) for _, ident, url, ts in items]
    log.info("catalog %s (cdx/wayback-first)", len(out))
    return out


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 30)
    max_seconds = env_int("MAX_SECONDS", 900)
    do_reprocess = os.environ.get("REPROCESS", "1") not in ("0", "false", "no")
    reproc_n = 0

    if do_reprocess:
        reproc_n = reprocess_existing()
        log.info("reprocess improved=%s", reproc_n)
        rebuild_index()

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
    if max_new > 0:
        for ident, url, ts in discover():
            if max_new and ok >= max_new:
                break
            if target_total and (already + ok) >= target_total:
                break
            if time.time() - t_start > max_seconds:
                log.info("time budget exhausted")
                break
            rid = slug_id(CC, ident)
            nu = _norm_url(url).lower()
            if rid in done or nu in have_urls:
                skip += 1
                continue
            if ts:
                got = _wayback_fetch(url, ts)
            else:
                got = fetch_official(url, ua=UA, min_text=200, wayback_ts=None)
                if got.get("status") != "success":
                    got = _wayback_fetch(url, None)
            text = got.get("text") or ""
            if got.get("status") != "success":
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error"), "wayback_ts": ts})
                continue
            if len(text) > 2_500_000:
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_too_large", "chars": len(text)})
                continue
            title = _title_from_text(text, ident)
            blob = f"{ident}|{title}|{url}|{text[:2500]}"
            if JUNK_RE.search(blob) and not ACT_TEXT_RE.search(blob):
                skip += 1
                log.info("skip junk post-fetch %s", ident[:60])
                continue
            if not re.search(
                r"(?i)\b(act|constitution|chapter\s+\d+|statutory\s+instrument|"
                r"arrangement\s+of\s+sections|parliament\s+of\s+zimbabwe|"
                r"republic\s+of\s+zimbabwe|gazetted?|bill)\b",
                text[:2500],
            ):
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": "non_lawish_text", "wayback_ts": ts})
                continue
            if save_zw_instrument(
                ident=ident,
                title=title or ident,
                text=text,
                source_url=_norm_url(url),
                extra_meta={"fetch_method": got.get("method"), "wayback_ts": ts},
            ):
                ok += 1
                done.add(rid)
                have_urls.add(nu)
                log.info("ok %s method=%s chars=%s title=%s", ident[:55], got.get("method"), len(text), (title or "")[:55])
            else:
                fail += 1

    n_inst = rebuild_index()
    arts = 0
    for p in (ROOT / CC / "instruments").glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        arts += int(rec.get("article_count") or len(rec.get("documents") or []) or 0)

    write_summary(
        CC, country=COUNTRY,
        source="Zimbabwe Official Gazette / Acts (parlzim.gov.zw / justice.gov.zw / zim.gov.zw / opc.gov.zw)",
        source_urls=[
            "https://www.parlzim.gov.zw/",
            "https://www.justice.gov.zw/",
            "https://www.zim.gov.zw/",
            "https://www.opc.gov.zw/",
            "https://www.mopse.gov.zw/",
        ],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (CDX/Wayback of official parlzim/justice/zim *.gov.zw PDFs; commonwealth section densify)",
        notes=(
            f"Official *.gov.zw PDFs only via CDX/Wayback. Commonwealth 1. Short title. split + "
            f"enacting-body prefer. reprocess_improved={reproc_n} instruments={n_inst} articles={arts}. "
            f"Not Veritas/AfricanLII/ZimbabweLII. No WAF bypass. Not legal advice."
        ),
        last_run=t0,
    )
    log.info(
        "done ok=%s skip=%s fail=%s reprocess=%s inst=%s arts=%s",
        ok, skip, fail, reproc_n, n_inst, arts,
    )


if __name__ == "__main__":
    main()
