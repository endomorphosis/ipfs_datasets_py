#!/usr/bin/env python3
"""Mauritius (mu): official Acts / Bills / SI / Gazette / Constitution PDFs.

Official only:
  - https://attorneygeneral.govmu.org/   (Attorney General's Office — Acts / Bills)
  - https://nationalassembly.govmu.org/  (National Assembly)
  - https://mauritiusassembly.govmu.org/
  - https://supremecourt.govmu.org/      (Supreme Court)
  - https://govmu.org/ / https://www.govmu.org/
  - Official Gazette / related *.govmu.org ministry law pages
  - Wayback/CDX of the same official *.govmu.org / *.mu URLs

Densify: Mauritius Acts use Commonwealth ``1. Short title.`` section numbering
(not only ``Section N``). Prefer enacting body after BE IT ENACTED / TOC to avoid
double-counting. Same pattern as collect_ug.py / collect_ls.py / collect_sz.py.

NOT AfricanLII, MauritiusLII, commercial DBs, gazettes.africa.
No WAF bypass. Live-first; Wayback of same official URL on fail.
Skip PDFs >12MB. Leave sc/km/mg alone. Not legal advice.
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

CC, COUNTRY, LANG = "mu", "Mauritius", "en"
SOURCE_TYPE = "mauritius_official_ago_assembly_gazette"
LICENSE = (
    "Republic of Mauritius — Attorney General's Office (attorneygeneral.govmu.org) / "
    "National Assembly (nationalassembly.govmu.org / mauritiusassembly.govmu.org) / "
    "Supreme Court (supremecourt.govmu.org) / Government Portal (govmu.org) / "
    "Official Gazette when published on *.govmu.org. Authentic Official Gazette / "
    "Act text prevails. Not AfricanLII / MauritiusLII. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://attorneygeneral.govmu.org/)"

# Commonwealth body sections: "1. Short title." / "12A. Interpretation." PLUS classic Section N
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|Regulation|Reg\.)\s+[0-9]+[A-Za-z]?|"
    r"\d+[A-Za-z]?\.)(?=\s+[A-Z\"'(])"
)
ART_ONLY = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+[A-Za-z]?)\b")
ACT_TEXT_RE = re.compile(
    r"(?i)(AN ACT\b|A BILL\b|BE IT ENACTED|ARRANGEMENT OF|"
    r"This Act may be cited|These regulations may|Short title|"
    r"Statutory Instrument|S\.I\.\s*\d|Government Notice|G\.N\.\s*\d|"
    r"CONSTITUTION OF|OFFICIAL GAZETTE|GOVERNMENT GAZETTE|"
    r"Date of Assent|I assent|Revised Laws|"
    r"PENAL CODE|CIVIL CODE|CRIMINAL PROCEDURE|"
    r"THE [A-Z][A-Z0-9 \-\(\)]{8,80} ACT\b)"
)
ACT_URL_RE = re.compile(
    r"(?i)(/act[-_ ]|\bact[-_ ]|_act\.|-act\.|act\.pdf|constitution|"
    r"/bill[-_ ]|_bill\.|-bill\.|regulation|statutory|government.?notice|"
    r"revised.?laws|laws.?of.?mauritius|gn[_\-\s]?\d)"
)
JUNK_RE = re.compile(
    r"(?i)(press[_\-\s]?release|newsletter|vacancy|tender|brochure|"
    r"strategic[_\-\s]?plan|annual[_\-\s]?report|statistical[_\-\s]?report|"
    r"calendar|poster|leaflet|facebook|twitter|youtube|"
    r"banner|logo|photo|recruitment|application[_\-\s]?form|"
    r"speech|manifesto|budget[_\-\s]?speech|"
    r"order[_\-\s]?paper|parliamentary[_\-\s]?questions|private[_\-\s]?notice|"
    r"debate[_\-\s]?no|_debates|hansard|sitting|"
    r"market[_\-\s]?sounding|bid[_\-\s]?submission|procurement|"
    r"job[_\-\s]?vacancy|expression[_\-\s]?of[_\-\s]?interest|"
    r"findings[_\-\s]?on[_\-\s]?onsite|statisticalquestionnaire|"
    r"guidance[_\-\s]?for[_\-\s]?small[_\-\s]?law)"
)
log = logging.getLogger("mu")
MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED_SUFFIXES = (
    "govmu.org",
    "gov.mu",
    "attorneygeneral.govmu.org",
    "nationalassembly.govmu.org",
    "mauritiusassembly.govmu.org",
    "supremecourt.govmu.org",
    "govmu.org",
)
ALLOWED_EXACT = (
    "govmu.org",
    "www.govmu.org",
    "gov.mu",
    "www.gov.mu",
    "attorneygeneral.govmu.org",
    "www.attorneygeneral.govmu.org",
    "nationalassembly.govmu.org",
    "www.nationalassembly.govmu.org",
    "mauritiusassembly.govmu.org",
    "www.mauritiusassembly.govmu.org",
    "supremecourt.govmu.org",
    "www.supremecourt.govmu.org",
)

BLOCK_HOST = re.compile(
    r"(africanlii|saflii|commonlii|gazettes\.africa|"
    r"law\.africa|ulii\.org|worldlii|bailii|mauritiuslii|"
    r"seylii|kenyalaw|ulii)",
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
    r"legislation|/uploads/|/sites/default/files/|"
    r"lois|decret|decree|gn[_\-\s]?\d|government[_\-\s]?notice|"
    r"revised[_\-\s]?laws|rlm|laws[_\-\s]?of[_\-\s]?mauritius"
    r")",
    re.I,
)
DROP_RE = re.compile(
    r"(africanlii|mauritiuslii|saflii|gazettes\.africa|law\.africa|"
    r"press[_\-\s]?release|newsletter|vacancy|tender|brochure|"
    r"strategic[_\-\s]?plan|annual[_\-\s]?report|statistical[_\-\s]?report|"
    r"calendar|poster|leaflet|facebook|twitter|youtube|"
    r"banner|logo|photo|recruitment|application[_\-\s]?form|"
    r"speech|manifesto|budget[_\-\s]?speech|"
    r"seychelles|comoros|madagascar|"
    r"order[_\-\s]?paper|parliamentary[_\-\s]?questions|private[_\-\s]?notice|"
    r"debate[_\-\s]?no|_debates|act\d+_debates|market[_\-\s]?sounding|bid[_\-\s]?submission|"
    r"job[_\-\s]?vacancy|procurement|expression[_\-\s]?of[_\-\s]?interest)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"("
    r"REPUBLIC OF MAURITIUS|MAURITIUS|"
    r"AN ACT\b|A BILL\b|BE IT ENACTED|"
    r"Short title|This Act may be cited|"
    r"OFFICIAL GAZETTE|GOVERNMENT GAZETTE|"
    r"Statutory Instrument|S\.I\.\s*\d|Government Notice|G\.N\.\s*\d|"
    r"CONSTITUTION OF (THE REPUBLIC OF )?MAURITIUS|"
    r"ARRANGEMENT OF SECTIONS|"
    r"National Assembly|President of the Republic|"
    r"Date of Assent|I assent|"
    r"Attorney[_\-\s]?General|Revised Laws|"
    r"PENAL CODE|CIVIL CODE|CRIMINAL PROCEDURE|"
    r"THE [A-Z][A-Z0-9 \-\(\)]{8,80} ACT\b"
    r")",
    re.I,
)

LIVE_PAGES = (
    "https://attorneygeneral.govmu.org/",
    "https://attorneygeneral.govmu.org/Pages/Laws%20of%20Mauritius.aspx",
    "https://attorneygeneral.govmu.org/Pages/Acts.aspx",
    "https://attorneygeneral.govmu.org/Pages/Bills.aspx",
    "https://attorneygeneral.govmu.org/Pages/Regulations.aspx",
    "https://attorneygeneral.govmu.org/Pages/Legal%20Services.aspx",
    "https://attorneygeneral.govmu.org/English/Pages/default.aspx",
    "https://attorneygeneral.govmu.org/English/Documents/Pages/default.aspx",
    "https://nationalassembly.govmu.org/",
    "https://nationalassembly.govmu.org/Pages/default.aspx",
    "https://nationalassembly.govmu.org/English/Pages/default.aspx",
    "https://nationalassembly.govmu.org/English/bills/Pages/default.aspx",
    "https://nationalassembly.govmu.org/English/acts/Pages/default.aspx",
    "https://mauritiusassembly.govmu.org/",
    "https://mauritiusassembly.govmu.org/English/Pages/default.aspx",
    "https://mauritiusassembly.govmu.org/English/bills/",
    "https://mauritiusassembly.govmu.org/English/acts/",
    "https://mauritiusassembly.govmu.org/mauritiusassembly/",
    "https://supremecourt.govmu.org/",
    "https://supremecourt.govmu.org/Pages/default.aspx",
    "https://supremecourt.govmu.org/English/Pages/default.aspx",
    "https://govmu.org/",
    "https://www.govmu.org/",
    "https://www.govmu.org/English/Pages/default.aspx",
    "https://mof.govmu.org/",
    "https://pmo.govmu.org/",
    "https://justice.govmu.org/",
)

WP_BASES = (
    "https://attorneygeneral.govmu.org",
    "https://nationalassembly.govmu.org",
    "https://mauritiusassembly.govmu.org",
    "https://mauritiusassembly.govmu.org/mauritiusassembly",
)

CDX_PREFIXES = (
    "attorneygeneral.govmu.org/",
    "www.attorneygeneral.govmu.org/",
    "attorneygeneral.govmu.org/Documents/",
    "attorneygeneral.govmu.org/English/Documents/",
    "attorneygeneral.govmu.org/sites/default/files/",
    "nationalassembly.govmu.org/",
    "www.nationalassembly.govmu.org/",
    "nationalassembly.govmu.org/Documents/",
    "nationalassembly.govmu.org/English/",
    "mauritiusassembly.govmu.org/",
    "www.mauritiusassembly.govmu.org/",
    "mauritiusassembly.govmu.org/English/",
    "mauritiusassembly.govmu.org/mauritiusassembly/wp-content/uploads/",
    "supremecourt.govmu.org/",
    "www.supremecourt.govmu.org/",
    "supremecourt.govmu.org/Documents/",
    "govmu.org/",
    "www.govmu.org/",
    "www.govmu.org/English/",
    "pmo.govmu.org/",
    "mof.govmu.org/",
    "justice.govmu.org/",
    "agc.govmu.org/",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if not host or BLOCK_HOST.search(host):
        return False
    if host in ALLOWED_EXACT:
        return True
    if host.endswith(".govmu.org") or host == "govmu.org":
        return True
    if host.endswith(".gov.mu") or host == "gov.mu":
        return True
    return any(host == s or host.endswith("." + s) for s in ALLOWED_SUFFIXES)


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _ident_from_url(url: str) -> str:
    host = (urlsplit(url).hostname or "mu").lower().replace("www.", "")
    stem = Path(unquote(urlsplit(url).path)).stem
    stem = re.sub(r"[^\w\-]+", "-", stem).strip("-").lower()
    pfx = host.split(".")[0]
    if pfx in ("gov", "www", "govmu"):
        pfx = "govmu"
    return f"{pfx}-{stem}"[:160]


def _priority(name: str) -> int:
    low = name.lower()
    if re.search(r"constitut", low):
        return 1
    if re.search(r"penal.?code|civil.?code|criminal.?procedure|revised.?laws", low):
        return 3
    if re.search(r"(^|[/_\-])act|amendment.?act", low):
        return 8
    if re.search(r"\bbill\b", low):
        return 12
    if re.search(r"regulation|statutory|\bsi[_\-\s]?\d|s\.i|government.?notice|\bgn[_\-\s]?\d", low):
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
            r"(?i)(/act[-_ ]|\bact[-_ ]|amendment.?act|constitution.of|"
            r"penal.?code|civil.?code|/si[-_ ]|\bsi[-_ ]?\d|statutory|"
            r"official.?gazette|bill.?no|government.?notice|revised.?laws|"
            r"laws.?of.?mauritius)",
            blob,
        ):
            return False
        if re.search(
            r"(?i)(press.?release|statistical.?report|strategic.?plan|"
            r"annual.?report|poster|leaflet|budget.?speech|vacancy|"
            r"order.?paper|parliamentary.?questions|debate.?no|"
            r"market.?sounding|bid.?submission|procurement)",
            blob,
        ):
            return False
    host = (urlsplit(url).hostname or "").lower()
    if "attorneygeneral" in host and re.search(
        r"(?i)(act|bill|si|s\.i|gazette|regulation|constitution|gn|law)", blob
    ):
        return True
    if ("nationalassembly" in host or "mauritiusassembly" in host) and re.search(
        r"(?i)(act|bill|si|s\.i|gazette|constitution)", blob
    ):
        return bool(KEEP_RE.search(blob))
    if "supremecourt" in host and re.search(
        r"(?i)(constitution|code|act|rules|procedure|practice)", blob
    ):
        return True
    return bool(KEEP_RE.search(blob))


def prefer_enacting_body(text: str) -> str:
    """Skip arrangement/TOC so article split targets operative sections."""
    if not text:
        return text
    m = re.search(r"(?is)BE IT ENACTED[^\n]*\n", text)
    if m and m.end() < len(text) - 200:
        return text[m.end() :]
    # Mauritius Constitution: "1. The State" after TOC
    ones_state = list(re.finditer(r"(?im)^\s*1\.\s+The State\b", text))
    if len(ones_state) >= 2:
        return text[ones_state[1].start() :]
    if len(ones_state) == 1:
        # single body occurrence after arrangement
        arr = re.search(r"(?i)ARRANGEMENT OF SECTIONS", text)
        if arr and ones_state[0].start() > arr.start():
            return text[ones_state[0].start() :]
    body_ones = list(
        re.finditer(
            r"(?im)^\s*1\.\s+(?:This Act|These Regulations|These regulations)\b",
            text,
        )
    )
    if body_ones:
        return text[body_ones[0].start() :]
    ones = list(re.finditer(r"(?im)^\s*1\.\s+(?:Short title|Citation)\b", text))
    if len(ones) >= 2:
        return text[ones[1].start() :]
    m = re.search(r"(?i)ARRANGEMENT OF (?:SECTIONS|RULES|ORDERS)", text)
    if m:
        parts = list(re.finditer(r"(?im)^\s*PART\s+I\b", text))
        if len(parts) >= 2:
            return text[parts[1].start() :]
    return text


def split_mu_articles(text: str, rid: str, source_url: str, date=None) -> list:
    """Commonwealth ``1. Title.`` body split by default.

    Mauritius Constitution uses section numbers (``1. The State``), not Articles —
    prefer dense commonwealth sections when present.
    """
    body = prefer_enacting_body(text)
    docs_sec = split_custom(body, rid, source_url, date, ART)
    docs_art = split_custom(body, rid, source_url, date, ART_ONLY)
    blob = f"{rid}|{source_url}"
    is_const = bool(re.search(r"(?i)constitution", blob)) and not bool(
        re.search(r"(?i)amm?endment", blob)
    )
    if is_const:
        # Mauritius Const is Commonwealth-numbered; avoid sparse Article false-positives
        if len(docs_sec) >= 20:
            return docs_sec
        if len(docs_art) >= 20:
            return docs_art
        if len(docs_art) >= 2 and len(docs_sec) > max(20, len(docs_art) * 3):
            return docs_art
        if len(docs_art) < 2:
            return docs_art
    if len(docs_art) >= 50 and len(docs_art) > len(docs_sec) * 1.2:
        return docs_art
    return docs_sec


def save_mu_instrument(
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
    docs = split_mu_articles(text, rid, source_url, None)
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
        collector="collect_mu.py",
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
            r"This Act may be cited|These regulations may|Short title|"
            r"CONSTITUTION|Government Gazette|OFFICIAL GAZETTE|Revised Laws|"
            r"AN ACT\b|A BILL\b",
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
        docs = split_mu_articles(text, rid, url, date)
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
        meta["article_reprocess"] = "collect_mu.py-commonwealth-sections"
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


def _scrape_page_pdfs(page_url: str) -> list[tuple[str, str]]:
    try:
        r = live_get(page_url, ua=UA, timeout=(15, 45), retries=2)
    except Exception as exc:
        log.info("page %s err %s", page_url, exc)
        return []
    if getattr(r, "status_code", 0) != 200 or not getattr(r, "text", None):
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
    for m in re.finditer(
        r'href=["\']([^"\']*(?:Documents|download|FileDownload)[^"\']*)["\']',
        html,
        re.I,
    ):
        href = m.group(1).replace("&amp;", "&")
        if ".pdf" not in href.lower() and "pdf" not in href.lower():
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = urljoin(page_url, href)
        elif not href.startswith("http"):
            href = urljoin(page_url, href)
        title = unquote(Path(urlsplit(href).path).stem).replace("-", " ").replace("_", " ")
        found.append((href, title or "document"))
    return found


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
        time.sleep(0.12)

    for base in WP_BASES:
        for page in range(1, 5):
            api = (
                f"{base}/wp-json/wp/v2/media"
                f"?per_page=100&page={page}&mime_type=application/pdf"
                f"&orderby=date&order=desc"
            )
            try:
                r = live_get(api, ua=UA, timeout=(15, 45), retries=1)
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
            time.sleep(0.1)

    if env_int("INCLUDE_CDX_PDF", 1):
        for prefix in CDX_PREFIXES:
            try:
                hits = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 120),
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
                # also normalize :80 quirk
                have_urls.add(u.lower().replace(":80/", "/"))
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
        nu = url.split("#")[0].strip().lower().replace(":80/", "/")
        if rid in done or nu in have_urls:
            skip += 1
            continue
        if size_hint and size_hint > MAX_PDF_BYTES:
            skip += 1
            continue
        # deprioritize weak gazette/misc once we have enough new acts
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
        if save_mu_instrument(
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
            "Mauritius Attorney General's Office (attorneygeneral.govmu.org) / "
            "National Assembly / Supreme Court / govmu.org"
        ),
        source_urls=[
            "https://attorneygeneral.govmu.org/",
            "https://nationalassembly.govmu.org/",
            "https://mauritiusassembly.govmu.org/",
            "https://supremecourt.govmu.org/",
            "https://govmu.org/",
            "https://www.govmu.org/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (attorneygeneral.govmu.org + "
            "nationalassembly/mauritiusassembly.govmu.org + supremecourt.govmu.org + "
            "govmu.org live+CDX; commonwealth section densify; PDFs >12MB skipped)"
        ),
        notes=(
            f"Official *.govmu.org / attorneygeneral / nationalassembly / "
            f"mauritiusassembly / supremecourt / govmu only. Commonwealth 1. section "
            f"split + enacting-body prefer. instruments={n_inst} articles={arts}. "
            f"Live-first; Wayback/CDX of same official URLs. NOT AfricanLII / "
            f"MauritiusLII. No WAF bypass. Not legal advice. mu=Mauritius (not sc/km/mg)."
        ),
        last_run=t0,
    )
    log.info(
        "done ok=%s skip=%s fail=%s instruments=%s articles=%s",
        ok, skip, fail, n_inst, arts,
    )


if __name__ == "__main__":
    main()
