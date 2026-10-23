#!/usr/bin/env python3
"""Liberia (lr): official Acts / gazettes PDFs via *.gov.lr.

Official only:
  - senate.gov.lr / house.gov.lr / legislature.gov.lr (legislature)
  - moj.gov.lr / judiciary.gov.lr (justice)
  - emansion.gov.lr / micat.gov.lr / gov.lr (executive / gazette hosts)
  - lla.gov.lr / fda.gov.lr / lra.gov.lr / mfdp.gov.lr / cndra.gov.lr /
    epa.gov.lr / leiti.gov.lr / lacc.gov.lr / ppcc.gov.lr and other *.gov.lr
  - Wayback/CDX of the same official *.gov.lr URLs

NOT LiberLII / AfricanLII / commercial DBs as source text.
No WAF bypass. Skip PDFs >12MB. Not legal advice.

Densify: Commonwealth ``1. Short title.`` + Liberian ``Section N`` / ``§ 101``
numbering. Prefer enacting body after BE IT ENACTED / ``It is enacted by the
Senate`` / TOC (ug/mu/na/sl/gm pattern) to avoid double-counting arrangement.
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

CC, COUNTRY, LANG = "lr", "Liberia", "en"
SOURCE_TYPE = "liberia_official_gazette_acts"
LICENSE = (
    "Republic of Liberia — Senate (senate.gov.lr) / House (house.gov.lr) / "
    "Legislature / Ministry of Justice (moj.gov.lr) / Judiciary (judiciary.gov.lr) / "
    "Executive Mansion (emansion.gov.lr) / MICAT / LLA / other *.gov.lr gazette hosts. "
    "Authentic Official Gazette / Act text prevails. "
    "Not LiberLII as LII source text. Not AfricanLII. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://senate.gov.lr/)"

# Commonwealth "1. Short title." + Liberian Section/Article/§ 101 PLUS classic markers
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|Cap\.?|Chapter|Part)\s*[0-9]+[A-Za-z]?|"
    r"§\s*[0-9]+[A-Za-z]?\.?|"
    r"\d+[A-Za-z]?\.)(?=\s*(?:[A-Z\"'(]|In |This |These |The |For |Short |Definitions))"
)
ART_ONLY = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+[A-Za-z]?)\b")

ACT_TEXT_RE = re.compile(
    r"(?i)(?:BE IT ENACTED|It is enacted by the Senate|ARRANGEMENT OF SECTIONS|"
    r"STATUTORY INSTRUMENTS?|SUPPLEMENT No\.|Act No\.|This Act may be cited|"
    r"Short title|AN ACT\b|A BILL\b|Liberian Code of Laws|Title \d+|"
    r"THE\s+[A-Z][A-Z0-9 \-',()]{6,90}\s+ACT,?\s*\d{4})"
)
ACT_URL_RE = re.compile(
    r"(?i)(?:_act\.pdf|act\.pdf|act%20|/acts?/|constitution|statutory|gazette|"
    r"wp-content/uploads|sites/default/files|policies-laws|download=|"
    r"law-database|document-type/acts)"
)
JUNK_RE = re.compile(
    r"(?i)annual.?report|strategic.?plan|press.?release|speech|budget.?speech|"
    r"workshop|seminar|brochure|flyer|vacancy|tender|procurement|"
    r"manifesto|powerpoint|\bppt\b|newsletter|progress.?report|"
    r"remarks.?by.?his.?excellency|asset.?declaration|"
    r"transcript.?of|policy.?brief|consultation|"
    r"environmental.?and.?social.?management.?framework|"
    r"paving.?the.?way|institutional.?corruption.?risk|"
    r"service.?delivery.?charter|email.?policy|software.?acquisition|"
    r"it.?asset.?disposal|circular.?no|notice.?of.?publication|"
    r"expression.?of.?interest|terms.?of.?reference|"
    r"application.?form|organigram|biograph"
)

log = logging.getLogger("lr")

HOMES = [
    "https://senate.gov.lr/",
    "https://senate.gov.lr/document-category/act/",
    "https://house.gov.lr/",
    "https://www.moj.gov.lr/",
    "https://www.moj.gov.lr/index.php/publications/document-type/acts",
    "https://judiciary.gov.lr/",
    "https://www.emansion.gov.lr/",
    "https://www.micat.gov.lr/",
    "https://lla.gov.lr/",
    "https://lla.gov.lr/index.php/downloadable-resources/policies-laws-regulations-repository",
    "https://lla.gov.lr/index.php/downloadable-resources/policies-laws-regulations-repository?start=20",
    "https://lla.gov.lr/index.php/downloadable-resources/policies-laws-regulations-repository?start=40",
    "https://lla.gov.lr/index.php/downloadable-resources/policies-laws-regulations-repository?start=60",
    "https://lla.gov.lr/index.php/downloadable-resources/policies-laws-regulations-repository?start=80",
    "https://fda.gov.lr/",
    "https://fda.gov.lr/index.php/general/liberia-law-database",
    "https://www.lra.gov.lr/",
    "https://www.mfdp.gov.lr/",
    "https://www.epa.gov.lr/",
    "https://www.leiti.gov.lr/",
    "https://www.lacc.gov.lr/",
    "https://www.ppcc.gov.lr/",
    "https://www.cndra.gov.lr/",
]

ALLOWED = ("gov.lr",)
DROP_RE = re.compile(
    r"(liberlii|africanlii|law\.africa|gazettes\.africa|"
    r"/news/|/videos?/|interview|facebook|youtube|twitter|logo|banner|photo|"
    r"recruitment|vacancy|newsletter|tender|procurement|job[_-]?announcement|"
    r"press[_-]?release|strategic.?plan|annual.?report|brochure|flyer|calendar|consultants-reports|knowledge-products|"
    r"factsheet|application.?form|speech|budget.?speech|manifesto|cv[-_]|"
    r"biograph|organigram|presentation|workshop|seminar|powerpoint|\bppt\b|"
    r"invitation.?for.?bid|personal.?protective)",
    re.I,
)
KEEP_RE = re.compile(
    r"(act|acts|bill|statute|ordinance|proclamation|gazette|law|legal|"
    r"constitution|subsidiary|instrument|regulation|order|cap\.?\s*\d|"
    r"amendment|decree|statutory.?instrument|\bSI\b|legislation|"
    r"document-category/act|publications/document-type/acts|"
    r"policies-laws|law-database|liberia.?law|download=)",
    re.I,
)
MAX_PDF_BYTES = 12 * 1024 * 1024

SEED_PDFS = [
    "https://senate.gov.lr/wp-content/uploads/2024/09/Act-to-establish-the-Liberia-Revenue-Authority-2013.pdf",
    "https://www.moj.gov.lr/sites/default/files/documents/foi-act.pdf",
    "https://www.moj.gov.lr/sites/default/files/documents/police-act.pdf",
    "https://fda.gov.lr/sites/default/files/documents/constitution-of-the-republic-of-libera-1984-ext-en.pdf",
    "https://fda.gov.lr/sites/default/files/documents/act-2002-act-creating-the-environment-protection-agency-of-the-republic-of-liberia-abstract-ext-en.pdf",
    "https://judiciary.gov.lr/wp-content/uploads/2015/10/Court-Costs-Fees-Fines_opt.pdf",
]

CDX_PREFIXES = (
    "senate.gov.lr/",
    "www.senate.gov.lr/",
    "house.gov.lr/",
    "www.house.gov.lr/",
    "moj.gov.lr/",
    "www.moj.gov.lr/",
    "judiciary.gov.lr/",
    "www.judiciary.gov.lr/",
    "emansion.gov.lr/",
    "www.emansion.gov.lr/",
    "micat.gov.lr/",
    "www.micat.gov.lr/",
    "lla.gov.lr/",
    "www.lla.gov.lr/",
    "fda.gov.lr/",
    "www.fda.gov.lr/",
    "lra.gov.lr/",
    "www.lra.gov.lr/",
    "mfdp.gov.lr/",
    "www.mfdp.gov.lr/",
    "gov.lr/",
    "www.gov.lr/",
    "epa.gov.lr/",
    "www.epa.gov.lr/",
    "leiti.gov.lr/",
    "www.leiti.gov.lr/",
    "lacc.gov.lr/",
    "www.lacc.gov.lr/",
    "cndra.gov.lr/",
    "www.cndra.gov.lr/",
    "ppcc.gov.lr/",
    "www.ppcc.gov.lr/",
    "moci.gov.lr/",
    "www.moci.gov.lr/",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if any(x in host for x in ("liberlii", "africanlii", "gazettes.africa", "law.africa")):
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
    """Skip arrangement/TOC so article split targets operative sections."""
    if not text:
        return text

    m = re.search(r"(?is)(?:BE IT ENACTED|It is enacted by the Senate)[^\n]*\n", text)
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

    m = re.search(r"(?i)ARRANGEMENT OF (?:SECTIONS|RULES|ORDERS)|Arrangement of Sections", text)
    if m:
        after = text[m.end() :]
        body = list(
            re.finditer(
                r"(?im)^\s*1\.\s*(?:Short title|Citation|Interpretation|Definitions|"
                r"This Act|In this Act|The Republic)\b",
                after,
            )
        )
        if len(body) >= 2:
            return after[body[-1].start() :]
        if len(body) == 1:
            # single post-TOC "1. …" may still be TOC line; prefer CHAPTER I second
            pass
        chapters = list(re.finditer(r"(?im)^\s*CHAPTER\s+I\b", text))
        if len(chapters) >= 2:
            return text[chapters[1].start() :]
        parts = list(re.finditer(r"(?im)^\s*PART\s+I\b", after))
        if len(parts) >= 2:
            return after[parts[1].start() :]
        if body:
            return after[body[0].start() :]
    return text


def split_lr_articles(text: str, rid: str, source_url: str, date=None) -> list:
    """Commonwealth/Liberian ``1.`` / ``§ N`` body split; constitutions prefer Article N."""
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
            # Liberian constitution reprints may use Article N; prefer when dense
            return docs_sec if docs_sec else docs_art
    if len(docs_art) >= 50 and len(docs_art) > len(docs_sec) * 1.2:
        return docs_art
    return docs_sec


def save_lr_instrument(
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
    docs = split_lr_articles(text, rid, source_url, None)
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
        collector="collect_lr.py",
        documents=docs,
        extra_meta=meta,
    )
    write_instrument(CC, rec)
    return True


def _is_act_like(rec: dict, name: str) -> bool:
    text = rec.get("text") or ""
    blob = f"{name}|{rec.get('title') or ''}|{rec.get('source_url') or ''}|{text[:3000]}"
    if JUNK_RE.search(blob) and not ACT_TEXT_RE.search(blob):
        return False
    return bool(
        ACT_TEXT_RE.search(blob)
        or (ACT_URL_RE.search(blob) and ACT_TEXT_RE.search(text[:8000]))
    )


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
        docs = split_lr_articles(text, rid, url, date)
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
        meta["article_reprocess"] = "collect_lr.py-commonwealth-sections"
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
    """Return list of (ident, url, wayback_ts|None). Live homes + CDX PDFs."""
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
        is_lla_dl = bool(re.search(r"(?i)[?&]download=", low))
        is_doc_dl = bool(
            re.search(
                r"(?i)(linkclick\.aspx|fileticket=|/download|/file\.aspx|/getfile|"
                r"/document/|/wp-content/uploads|/sites/default/files|"
                r"index\.php/.*/download|[?&]download=)",
                low,
            )
        )
        # Live LLA repository uses ?download=slug (no .pdf in URL)
        if not is_pdf_ext and not is_lla_dl and not (from_cdx_pdf and is_doc_dl):
            return
        if not is_pdf_ext and (is_lla_dl or (from_cdx_pdf and is_doc_dl)):
            pass
        elif not KEEP_RE.search(blob):
            if not re.search(
                r"(?i)/(acts?|laws?|gazette|legislation|publications?|documents?|"
                r"downloads?|files?|uploads?|wp-content|statutory|si[_/\-]|cap[_/\-]|"
                r"policies-laws|law-database|document-category|bills?)",
                blob,
            ):
                return
        key = url.lower()
        if key in seen:
            return
        seen.add(key)
        m_dl = re.search(r"(?i)[?&]download=([^&]+)", url)
        if m_dl:
            ident = "lla-download-" + re.sub(r"\W+", "-", unquote(m_dl.group(1))).strip("-")[:120]
        else:
            ident = (
                re.sub(r"^https?://[^/]+/", "", unquote(url))
                .replace("/", "-")
                .replace("?", "-")[:160]
            )
        # Prefer LLA act downloads
        if m_dl and re.search(r"(?i)(act|law|code|constitution|regulation)", unquote(m_dl.group(1))):
            priority = min(priority, 8)
        items.append((priority, ident, url, ts))

    for seed in SEED_PDFS:
        if seed.rstrip("/").endswith(".pdf") or ".pdf" in seed.lower():
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
            hits = cdx_urls(
                prefix,
                limit=env_int("CDX_LIMIT", 250),
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
            if re.search(
                r"(?i)(act|gazette|constitution|statutory|/laws?/|/legislation|bill|"
                r"regulation|amendment)",
                unquote(orig),
            ):
                pri = 15
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
        if save_lr_instrument(
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
            "Liberia Official Gazette / Acts "
            "(senate.gov.lr / house.gov.lr / moj.gov.lr / judiciary.gov.lr / "
            "emansion.gov.lr / lla.gov.lr / fda.gov.lr)"
        ),
        source_urls=[
            "https://senate.gov.lr/",
            "https://house.gov.lr/",
            "https://www.moj.gov.lr/",
            "https://judiciary.gov.lr/",
            "https://www.emansion.gov.lr/",
            "https://lla.gov.lr/",
            "https://fda.gov.lr/",
            "https://www.gov.lr/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (PDF-first CDX *.gov.lr + live probes; "
            "commonwealth + Liberian § densify; LLA download repo)"
        ),
        notes=(
            f"Official *.gov.lr PDFs only. Commonwealth 1./§ Section split + enacting-body prefer. LLA policies-laws repo. "
            f"instruments={n_inst} articles={arts}. Not LiberLII/AfricanLII as source text. "
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
