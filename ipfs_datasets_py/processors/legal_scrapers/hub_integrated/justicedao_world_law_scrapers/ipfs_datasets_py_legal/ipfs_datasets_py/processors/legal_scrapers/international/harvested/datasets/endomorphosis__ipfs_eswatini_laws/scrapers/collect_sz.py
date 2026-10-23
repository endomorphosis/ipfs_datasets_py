#!/usr/bin/env python3
"""Eswatini / Swaziland (sz): official Acts / Bills / SI / Gazette / Constitution PDFs.

Official only (allowlist *.gov.sz / known official *.sz):
  - https://www.gov.sz/ / https://gov.sz/
  - https://www.parliament.gov.sz/ / https://parliament.gov.sz/
  - https://www.judiciary.org.sz/ / https://judiciary.org.sz/ (when official)
  - Attorney General / Ministry of Justice / Law / Gazette on *.gov.sz
  - Central Bank of Eswatini when on official *.sz
  - Wayback/CDX of the same official *.gov.sz / *.sz URLs

NOT EswatiniLII / SwazilandLII (eswatinilii.org / swazilii.org), AfricanLII, SAFLII,
gazettes.africa, commercial. No WAF bypass. Live-first; Wayback of same official URL
on fail. Densify: Eswatini Acts/regs use Commonwealth ``1. This Act may be cited`` /
``1. Short title.`` section numbering (not only ``Section N``).
Prefer enacting body after BE IT ENACTED / operative s.1 to avoid TOC double-count.

Skip PDFs >12MB. Leave ls/ug/sd alone. Not legal advice.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit, urljoin

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

CC, COUNTRY, LANG = "sz", "Eswatini", "en"
SOURCE_TYPE = "eswatini_official_gazette_acts"
LICENSE = (
    "Kingdom of Eswatini — Official government portals (gov.sz / parliament.gov.sz / "
    "related *.gov.sz and known official *.sz). Authentic Government Printer / "
    "Official Gazette / Act text prevails. Not EswatiniLII / AfricanLII. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.gov.sz/)"
# Commonwealth body sections: "1. This Act may be cited." / "12A. Interpretation." PLUS classic Section N
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|Regulation|Reg\.)\s+[0-9]+[A-Za-z]?|"
    r"\d+[A-Za-z]?\.)(?=\s+[A-Z\"'(])"
)
ART_ONLY = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+[A-Za-z]?)\b")
ACT_TEXT_RE = re.compile(
    r"(?i)(AN ACT\b|A BILL\b|BE IT ENACTED|ARRANGEMENT OF|"
    r"This Act may be cited|These regulations may|Short title|"
    r"Legal Notice|L\.N\.\s*\d|Statutory Instrument|S\.I\.\s*\d|"
    r"CONSTITUTION OF|Government Gazette|Official Gazette|"
    r"ENACTED by the King|I assent)"
)
ACT_URL_RE = re.compile(
    r"(?i)(/act[-_ ]|\bact[-_ ]|_act\.|-act\.|act\.pdf|constitution|"
    r"/bill[-_ ]|_bill\.|-bill\.|regulation|statutory|legal.?notice|"
    r"directive|guideline)"
)
JUNK_RE = re.compile(
    r"(?i)(bills/results|bond.?auction|bond.?advert|assets.?liabilit|"
    r"press.?release|newsletter|vacancy|tender|brochure|strategic.?plan|"
    r"annual.?report|statistical|calendar|poster|leaflet|speech|"
    r"facebook|twitter|youtube|banner|logo|photo|recruitment|"
    r"budget.?speech|competition|audit.?report|corona|covid|"
    r"mpc\b|monetary.?policy|organogram|bid.?form|community.?guidelines|"
    r"social.?media|pm.?statement|cleaning.?services)"
)
log = logging.getLogger("sz")
MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED_SUFFIXES = (
    "gov.sz",
    "parliament.gov.sz",
    "judiciary.org.sz",
    "centralbank.org.sz",
    "centralbank.sz",
    "info.gov.sz",
    "justice.gov.sz",
    "ag.gov.sz",
    "finance.gov.sz",
    "mof.gov.sz",
    "srai.org.sz",
)
ALLOWED_EXACT = (
    "gov.sz",
    "www.gov.sz",
    "parliament.gov.sz",
    "www.parliament.gov.sz",
    "judiciary.org.sz",
    "www.judiciary.org.sz",
    "centralbank.org.sz",
    "www.centralbank.org.sz",
    "centralbank.sz",
    "www.centralbank.sz",
    "info.gov.sz",
    "www.info.gov.sz",
    "justice.gov.sz",
    "www.justice.gov.sz",
    "ag.gov.sz",
    "www.ag.gov.sz",
    "finance.gov.sz",
    "www.finance.gov.sz",
    "mof.gov.sz",
    "www.mof.gov.sz",
)

BLOCK_HOST = re.compile(
    r"(eswatinilii|swazilii|swazilandlii|africanlii|saflii|commonlii|"
    r"gazettes\.africa|law\.africa|ulii\.org|worldlii|bailii|"
    r"lexisnexis|westlaw|swazilaw)",
    re.I,
)
KEEP_RE = re.compile(
    r"("
    r"\bact\b|_act_|-act-|act\.pdf|act%20|"
    r"\bbill\b|_bill_|-bill-|bill\.pdf|"
    r"regulation|regulations|"
    r"gazette|statutory[_\-\s]?instrument|\bsi[_\-\s]?\d|s\.i\.?\s*\d|"
    r"constitution|ordinance|proclamation|statute|"
    r"penal[_\-\s]?code|civil[_\-\s]?code|criminal[_\-\s]?procedure|"
    r"code[_\-\s]?of[_\-\s]?civil|commencement|amendment|"
    r"legislation|legal[_\-\s]?notice|\bln[_\-\s]?\d|"
    r"/uploads/|/sites/default/files/|/documents/|/download/|/images/"
    r")",
    re.I,
)
DROP_RE = re.compile(
    r"(eswatinilii|swazilii|swazilandlii|africanlii|saflii|gazettes\.africa|law\.africa|bills/results|"
    r"press[_\-\s]?release|newsletter|vacancy|tender|brochure|"
    r"strategic[_\-\s]?plan|annual[_\-\s]?report|statistical[_\-\s]?report|"
    r"annual[_\-\s]?integrated|annual[_\-\s]?economic|integrated[_\-\s]?report|"
    r"calendar|poster|leaflet|speech|manifesto|"
    r"facebook|twitter|youtube|banner|logo|photo|"
    r"recruitment|application[_\-\s]?form|budget[_\-\s]?speech|"
    r"bond[_\-\s]?advert|bond[_\-\s]?auction|bond[_\-\s]?results|assets[_\-\s]?liabilities|"
    r"gmw[_\-\s]?competition|competition|csr[_\-\s]?|cleaning[_\-\s]?services|"
    r"resettlement|action[_\-\s]?plan|quarterly[_\-\s]?review|audit[_\\-\\s]?report|auditor[_\\-\\s]?general|budget[_\\-\\s]?call|social[_\\-\\s]?media|community[_\\-\\s]?guidelines|pm[_\\-\\s]?statement|apm[_\\-\\s]?statement|intention[_\\-\\s]?to[_\\-\\s]?award|"
    r"lesotho|botswana|south[_\-\s]?africa|burundi|"
    r"party[_\-\s]?constitution)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"("
    r"AN ACT\b|A BILL\b|BE IT ENACTED|"
    r"Short title|This Act may be cited|"
    r"OFFICIAL GAZETTE|GOVERNMENT GAZETTE|"
    r"Legal Notice|L\.N\.\s*\d|Statutory Instrument|S\.I\.\s*\d|"
    r"CONSTITUTION OF (?:THE KINGDOM OF )?(?:ESWATINI|SWAZILAND)|"
    r"The Constitution of the Kingdom of (?:Eswatini|Swaziland)|"
    r"ARRANGEMENT OF SECTIONS|"
    r"Date of Assent|I assent|"
    r"PENAL CODE|CRIMINAL PROCEDURE|"
    r"ENACTED by the King|"
    r"published in the Government Gazette|"
    r"KINGDOM OF (?:ESWATINI|SWAZILAND).{0,80}(?:ACT|BILL|GAZETTE|NOTICE)"
    r")",
    re.I,
)

LIVE_PAGES = (
    "https://www.gov.sz/",
    "https://gov.sz/",
    "https://www.gov.sz/index.php/media/gazettes",
    "https://gov.sz/index.php/media/gazettes",
    "https://www.gov.sz/index.php/documents",
    "https://www.gov.sz/index.php/legislation",
    "https://www.gov.sz/index.php/laws",
    "https://www.gov.sz/index.php/services",
    "https://parliament.gov.sz/",
    "https://www.parliament.gov.sz/",
    "https://parliament.gov.sz/legislative/",
    "https://parliament.gov.sz/legislative/houseofassembly/",
    "https://parliament.gov.sz/legislative/senate/",
    "https://parliament.gov.sz/documents/",
    "https://parliament.gov.sz/bills/",
    "https://parliament.gov.sz/acts/",
    "https://www.judiciary.org.sz/",
    "https://judiciary.org.sz/",
    "https://www.judiciary.org.sz/legislation/",
    "https://www.judiciary.org.sz/laws/",
    "https://www.judiciary.org.sz/documents/",
    "https://www.centralbank.org.sz/",
    "https://www.centralbank.org.sz/legislation/",
    "https://centralbank.org.sz/",
    "https://www.info.gov.sz/",
    "https://info.gov.sz/",
    "https://www.justice.gov.sz/",
    "https://justice.gov.sz/",
    "https://www.ag.gov.sz/",
    "https://ag.gov.sz/",
    "https://www.finance.gov.sz/",
    "https://finance.gov.sz/",
    "https://www.mof.gov.sz/",
    "https://mof.gov.sz/",
)

WP_BASES = (
    "https://www.gov.sz",
    "https://parliament.gov.sz",
    "https://www.parliament.gov.sz",
    "https://www.judiciary.org.sz",
    "https://www.centralbank.org.sz",
    "https://www.info.gov.sz",
    "https://www.justice.gov.sz",
    "https://www.ag.gov.sz",
    "https://www.finance.gov.sz",
    "https://www.mof.gov.sz",
)

CDX_PREFIXES = (
    "www.gov.sz/",
    "gov.sz/",
    "www.parliament.gov.sz/",
    "parliament.gov.sz/",
    "www.judiciary.org.sz/",
    "judiciary.org.sz/",
    "www.centralbank.org.sz/",
    "centralbank.org.sz/",
    "www.info.gov.sz/",
    "info.gov.sz/",
    "www.justice.gov.sz/",
    "justice.gov.sz/",
    "www.ag.gov.sz/",
    "ag.gov.sz/",
    "www.finance.gov.sz/",
    "finance.gov.sz/",
    "www.mof.gov.sz/",
    "mof.gov.sz/",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if not host or BLOCK_HOST.search(host):
        return False
    if host in ALLOWED_EXACT:
        return True
    if host.endswith(".gov.sz") or host == "gov.sz":
        return True
    if host.endswith(".org.sz") and ("centralbank" in host or "judiciary" in host):
        return True
    return any(host == s or host.endswith("." + s) for s in ALLOWED_SUFFIXES)


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _ident_from_url(url: str) -> str:
    host = (urlsplit(url).hostname or "sz").lower().replace("www.", "")
    stem = Path(unquote(urlsplit(url).path)).stem
    stem = re.sub(r"[^\w\-]+", "-", stem).strip("-").lower()
    pfx = host.split(".")[0]
    if pfx in ("gov", "www"):
        pfx = "gov"
    return f"{pfx}-{stem}"[:160]


def _priority(name: str) -> int:
    low = name.lower()
    if re.search(r"constitut", low):
        return 1
    if re.search(r"penal.?code|civil.?code|criminal.?procedure", low):
        return 3
    if re.search(r"(^|[/_\-])act|amendment.?act", low):
        return 8
    if re.search(r"\bbill\b", low):
        return 12
    if re.search(r"regulation|statutory|\bsi[_\-\s]?\d|s\.i|legal.?notice|\bln[_\-\s]?\d", low):
        return 18
    if re.search(r"gazette", low):
        return 22
    return 30


def _should_keep(url: str, title: str = "") -> bool:
    blob = unquote(url) + " " + (title or "")
    if not _host_ok(url):
        return False
    if DROP_RE.search(blob):
        if not re.search(
            r"(?i)(/act[-_ ]|\bact[-_ ]|amendment.?act|constitution|"
            r"penal.?code|civil.?code|/si[-_ ]|\bsi[-_ ]?\d|statutory|"
            r"official.?gazette|government.?gazette|legal.?notice|bill.?no)",
            blob,
        ):
            return False
        if re.search(
            r"(?i)(party.?constitution|press.?release|statistical.?report|"
            r"strategic.?plan|annual.?report|poster|leaflet)",
            blob,
        ):
            return False
    host = (urlsplit(url).hostname or "").lower()
    if "parliament" in host:
        if re.search(r"(?i)(act|bill|si|s\.i|gazette|legal.?notice|constitution)", blob):
            return True
    if "judiciary" in host and re.search(r"(?i)(constitution|code|act|rules|procedure)", blob):
        return True
    if "centralbank" in host:
        return bool(re.search(
            r"(?i)(act|regulation|directive|statutory|legal.?notice|guideline|circular)",
            blob,
        )) and not DROP_RE.search(blob)
    # gov.sz often hosts Acts under /images/ paths
    if host.endswith("gov.sz") or host == "gov.sz":
        if re.search(r"(?i)(act|bill|gazette|regulation|constitution|notice|si[_\-\s]?\d)", blob):
            return True
    return bool(KEEP_RE.search(blob))


def _scrape_page_pdfs(page_url: str) -> list[tuple[str, str]]:
    try:
        r = live_get(page_url, ua=UA, timeout=(12, 35), retries=1)
    except Exception as exc:
        log.info("page %s err %s", page_url, exc)
        return []
    if getattr(r, "status_code", 0) != 200 or not getattr(r, "text", None):
        log.info("page %s status=%s", page_url, getattr(r, "status_code", None))
        return []
    html = r.text
    found: list[tuple[str, str]] = []
    for m in re.finditer(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.I):
        href = m.group(1).replace("&amp;", "&")
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = urljoin(page_url, href)
        elif not href.startswith("http"):
            href = urljoin(page_url, href)
        title = unquote(Path(urlsplit(href).path).stem).replace("-", " ").replace("_", " ")
        found.append((href, title))
    for m in re.finditer(r'(https?://[^\s"\'<>]+\.pdf)', html, re.I):
        href = m.group(1)
        title = unquote(Path(urlsplit(href).path).stem).replace("-", " ").replace("_", " ")
        found.append((href, title))
    return found



def prefer_enacting_body(text: str) -> str:
    """Skip arrangement/TOC so article split targets operative sections."""
    if not text:
        return text
    m = re.search(r"(?is)BE IT ENACTED[^\n]*\n", text)
    if m and m.end() < len(text) - 200:
        return text[m.end() :]
    body_ones = list(
        re.finditer(
            r"(?im)^\s*1\.\s+(?:This Act|These Regulations|These regulations)\b",
            text,
        )
    )
    if body_ones:
        return text[body_ones[0].start() :]
    heads = list(
        re.finditer(
            r"(?im)^\s*(Short title(?: and commencement)?|Citation and commencement)\s*$",
            text,
        )
    )
    if len(heads) >= 2:
        return text[heads[1].start() :]
    ones = list(re.finditer(r"(?im)^\s*1\.\s+(?:Short title|Citation)\b", text))
    if len(ones) >= 2:
        return text[ones[1].start() :]
    parts = list(re.finditer(r"(?im)^\s*PART\s+I\b", text))
    if len(parts) >= 2:
        return text[parts[1].start() :]
    return text


def split_sz_articles(text: str, rid: str, source_url: str, date=None) -> list:
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


def save_sz_instrument(
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
    docs = split_sz_articles(text, rid, source_url, None)
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
        collector="collect_sz.py",
        documents=docs,
        extra_meta=meta,
    )
    write_instrument(CC, rec)
    return True


def _is_junk_record(rec: dict, name: str) -> bool:
    title = rec.get("title") or ""
    url = rec.get("source_url") or ""
    text_head = (rec.get("text") or "")[:2500]
    blob = f"{name}|{title}|{url}|{text_head}"
    if ACT_TEXT_RE.search(blob) or ACT_URL_RE.search(blob):
        if re.search(
            r"(?i)Act No\.|_act\.pdf|BE IT ENACTED|ARRANGEMENT OF|"
            r"This Act may be cited|These regulations may|LEGAL NOTICE|"
            r"CONSTITUTION OF|Government Gazette|ENACTED by the King",
            blob,
        ):
            return False
        if ACT_TEXT_RE.search(text_head):
            return False
    return bool(JUNK_RE.search(blob))


def prune_junk() -> int:
    inst = ROOT / CC / "instruments"
    removed = 0
    for p in list(inst.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _is_junk_record(rec, p.name):
            p.unlink(missing_ok=True)
            removed += 1
            log.info("prune junk %s", p.name[:80])
    return removed


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
        docs = split_sz_articles(text, rid, url, date)
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
        meta["article_reprocess"] = "collect_sz.py-commonwealth-sections"
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
    """Return list of (priority, ident, url, ts|None, title, size_hint|None)."""
    items: list[tuple] = []
    seen: set[str] = set()

    def add(
        url: str,
        *,
        ident: str | None = None,
        title: str = "",
        ts: str | None = None,
        size_hint: int | None = None,
        priority: int | None = None,
    ):
        url = (url or "").split("#")[0].strip()
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        if "web.archive.org/web/" in url:
            m = re.search(r"https?://web\.archive\.org/web/\d+(?:id_)?/(https?://.*)", url)
            if m:
                url = m.group(1)
        if not url.startswith("http") or not _should_keep(url, title):
            return
        if ".pdf" not in url.lower():
            return
        key = url.lower()
        if key in seen:
            return
        seen.add(key)
        if size_hint and size_hint > MAX_PDF_BYTES:
            log.info("catalog skip >12MB sz=%s %s", size_hint, url.split("/")[-1][:60])
            return
        iid = ident or _ident_from_url(url)
        pri = priority if priority is not None else _priority(url + " " + title)
        items.append((pri, iid, url, ts, title or iid, size_hint))

    for page in LIVE_PAGES:
        for href, title in _scrape_page_pdfs(page):
            add(href, title=title)
        time.sleep(0.1)

    for base in WP_BASES:
        for page in range(1, 4):
            api = (
                f"{base}/wp-json/wp/v2/media"
                f"?per_page=100&page={page}&mime_type=application/pdf"
                f"&orderby=date&order=desc"
            )
            try:
                r = live_get(api, ua=UA, timeout=(12, 35), retries=1)
            except Exception as exc:
                log.info("wp media %s %s", base, exc)
                break
            if getattr(r, "status_code", 0) != 200:
                break
            try:
                rows = r.json()
            except Exception:
                break
            if not isinstance(rows, list) or not rows:
                break
            for it in rows:
                src = it.get("source_url") or ""
                title = _strip_html((it.get("title") or {}).get("rendered") or "")
                sz = None
                try:
                    sz = int((it.get("media_details") or {}).get("filesize") or 0) or None
                except Exception:
                    sz = None
                add(src, title=title, size_hint=sz)
            total_pages = int(r.headers.get("X-WP-TotalPages") or "1")
            if page >= total_pages:
                break
            time.sleep(0.08)

    if env_int("INCLUDE_CDX_PDF", 1):
        for prefix in CDX_PREFIXES:
            try:
                hits = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 80),
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
                stem = Path(unquote(urlsplit(orig).path)).stem
                add(orig, title=stem, ts=ts, size_hint=length or None)

    items.sort(key=lambda x: (x[0], x[1]))
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 2400)
    do_reprocess = os.environ.get("REPROCESS", "1") not in ("0", "false", "no")
    do_prune = os.environ.get("PRUNE_JUNK", "1") not in ("0", "false", "no")

    if do_reprocess:
        n = reprocess_existing()
        log.info("reprocess improved=%s", n)
    if do_prune:
        n = prune_junk()
        log.info("prune removed=%s", n)

    t_start = time.time()
    done = existing_ids(CC)
    have_urls: set[str] = set()
    for pth in (ROOT / CC / "instruments").glob("*.json"):
        try:
            u = (json.loads(pth.read_text(encoding="utf-8")).get("source_url") or "").split("#")[0].strip()
            if u:
                have_urls.add(u.lower())
        except Exception:
            pass

    already = len(done)
    target_total = env_int("TARGET_TOTAL", 0)
    ok = skip = fail = 0

    for pri, ident, url, ts, title, size_hint in discover():
        if max_new and ok >= max_new:
            break
        if target_total and (already + ok) >= target_total:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        nu = url.split("#")[0].strip().lower()
        if rid in done or nu in have_urls:
            skip += 1
            continue
        if size_hint and size_hint > MAX_PDF_BYTES:
            skip += 1
            continue
        if pri >= 22 and ok >= max(8, max_new // 3):
            skip += 1
            continue
        got = fetch_official(url, ua=UA, wayback=True, wayback_ts=ts)
        text_body = got.get("text") or ""
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
        if len(text_body) > 2_500_000:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_too_large"})
            continue
        use_title = title or first_title(text_body, ident)
        blob = f"{ident}|{use_title}|{url}|{text_body[:2500]}"
        if JUNK_RE.search(blob) and not ACT_TEXT_RE.search(blob):
            skip += 1
            log.info("skip junk post-fetch %s", ident[:60])
            continue
        if not TEXT_KEEP_RE.search(text_body[:12000]) and not ACT_TEXT_RE.search(blob):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_not_legal"})
            continue
        for line in text_body.splitlines():
            if len(line.strip()) > 18:
                use_title = line.strip()[:240]
                break
        if save_sz_instrument(
            ident=ident,
            title=use_title,
            text=text_body,
            source_url=url,
            extra_meta={
                "fetch_method": got.get("method"),
                "wayback_ts": ts,
                "size_hint": size_hint,
                "priority": pri,
            },
        ):
            ok += 1
            done.add(rid)
            have_urls.add(nu)
            log.info("ok %s method=%s chars=%s", ident[:60], got.get("method"), len(text_body))
        else:
            fail += 1

    n_inst = rebuild_index()
    arts = 0
    for pth in (ROOT / CC / "instruments").glob("*.json"):
        try:
            rec = json.loads(pth.read_text(encoding="utf-8"))
            arts += int(rec.get("article_count") or len(rec.get("documents") or []) or 0)
        except Exception:
            pass

    write_summary(
        CC,
        country=COUNTRY,
        source=(
            "Eswatini official *.gov.sz (gov / parliament / info / justice / ag / "
            "finance / mof) + judiciary.org.sz + centralbank.org.sz (legal only)"
        ),
        source_urls=[
            "https://www.gov.sz/",
            "https://parliament.gov.sz/",
            "https://www.judiciary.org.sz/",
            "https://www.centralbank.org.sz/",
            "https://www.info.gov.sz/",
            "https://www.justice.gov.sz/",
            "https://www.ag.gov.sz/",
            "https://www.finance.gov.sz/",
            "https://www.mof.gov.sz/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete thin honest set (*.gov.sz / judiciary.org.sz / "
            "parliament.gov.sz / centralbank.org.sz legal PDFs; commonwealth section densify; "
            "PDFs >12MB skipped; EswatiniLII/AfricanLII excluded)"
        ),
        notes=(
            f"Official *.gov.sz / judiciary.org.sz / centralbank.org.sz only. "
            f"Commonwealth 1. section split + enacting-body prefer. "
            f"instruments={n_inst} articles={arts}. "
            f"Live-first; Wayback/CDX of same official URLs. NOT EswatiniLII "
            f"(eswatinilii.org) / SwazilandLII / AfricanLII. No WAF bypass. "
            f"Not legal advice. sz=Eswatini (not ls/ug/sd)."
        ),
        last_run=t0,
    )
    log.info(
        "done ok=%s skip=%s fail=%s instruments=%s articles=%s",
        ok, skip, fail, n_inst, arts,
    )



if __name__ == "__main__":
    main()
