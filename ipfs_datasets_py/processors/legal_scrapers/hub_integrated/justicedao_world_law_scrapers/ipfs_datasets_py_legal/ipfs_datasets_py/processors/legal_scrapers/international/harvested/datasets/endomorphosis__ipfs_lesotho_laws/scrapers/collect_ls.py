#!/usr/bin/env python3
"""Lesotho (ls): official Acts / Bills / SI / Gazette / Constitution PDFs.

Official only (allowlist *.gov.ls / centralbank.org.ls):
  - https://www.gov.ls/
  - https://www.parliament.gov.ls/ / https://parliament.gov.ls/
  - https://www.nationalassembly.gov.ls/ / https://nationalassembly.gov.ls/
  - https://www.judiciary.gov.ls/ / https://judiciary.gov.ls/
  - https://www.law.gov.ls/ / https://law.gov.ls/
  - https://www.ag.gov.ls/ / https://ag.gov.ls/
  - https://www.centralbank.org.ls/ (legislation / Acts / regulations)
  - Wayback/CDX of the same official *.gov.ls / *.ls URLs

Densify: Lesotho Acts/regs use Commonwealth ``1. This Act may be cited`` /
``1. These regulations…`` section numbering (not only ``Section N``).
Prefer enacting body after BE IT ENACTED / operative s.1 to avoid TOC double-count.

NOT LesothoLII (lesotholii.org), AfricanLII, SAFLII, gazettes.africa, commercial.
No WAF bypass. Live-first; Wayback of same official URL on fail.
Skip PDFs >12MB. Leave ug/sz/sd alone. Not legal advice.
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

CC, COUNTRY, LANG = "ls", "Lesotho", "en"
SOURCE_TYPE = "lesotho_official_gazette_acts"
LICENSE = (
    "Kingdom of Lesotho — Official government portals (gov.ls / parliament.gov.ls / "
    "nationalassembly.gov.ls / judiciary.gov.ls / law.gov.ls / ag.gov.ls and related "
    "*.gov.ls) + centralbank.org.ls legislation. Authentic Government Printer / Official "
    "Gazette / Act text prevails. Not LesothoLII / AfricanLII. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.gov.ls/)"

# Commonwealth body sections: "1. This Act may be cited." / "12A. Interpretation." PLUS classic Section N
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|Regulation|Reg\.)\s+[0-9]+[A-Za-z]?|"
    r"\d+[A-Za-z]?\.)(?=\s+[A-Z\"'(])"
)
ART_ONLY = re.compile(r"(?im)^\s*((?:Article|Art\.?)\s+[0-9]+[A-Za-z]?)\b")

log = logging.getLogger("ls")
MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED_SUFFIXES = (
    "gov.ls",
    "parliament.gov.ls",
    "nationalassembly.gov.ls",
    "judiciary.gov.ls",
    "law.gov.ls",
    "ag.gov.ls",
    "senate.gov.ls",
    "justice.gov.ls",
    "finance.gov.ls",
    "centralbank.org.ls",
)
ALLOWED_EXACT = (
    "gov.ls",
    "www.gov.ls",
    "parliament.gov.ls",
    "nationalassembly.gov.ls",
    "judiciary.gov.ls",
    "law.gov.ls",
    "ag.gov.ls",
    "senate.gov.ls",
    "justice.gov.ls",
    "finance.gov.ls",
    "centralbank.org.ls",
    "www.centralbank.org.ls",
)

BLOCK_HOST = re.compile(
    r"(lesotholii|africanlii|saflii|commonlii|gazettes\.africa|"
    r"law\.africa|ulii\.org|worldlii|bailii|lesotholaws|"
    r"laws\.co\.ls|lexisnexis|westlaw)",
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
    r"/uploads/|/sites/default/files/|/documents/|/download/|"
    r"/images/Legislation|/legislation/"
    r")",
    re.I,
)
DROP_RE = re.compile(
    r"(lesotholii|africanlii|saflii|gazettes\.africa|law\.africa|"
    r"press[_\-\s]?release|newsletter|vacancy|tender|brochure|"
    r"strategic[_\-\s]?plan|annual[_\-\s]?report|statistical[_\-\s]?report|"
    r"calendar|poster|leaflet|speech|manifesto|"
    r"facebook|twitter|youtube|banner|logo|photo|"
    r"recruitment|application[_\-\s]?form|budget[_\-\s]?speech|"
    r"swaziland|eswatini|botswana|south[_\-\s]?africa|"
    r"party[_\-\s]?constitution|"
    r"\bmpc\b|monetary[_\-\s]?policy[_\-\s]?committee|monetary[_\-\s]?policy[_\-\s]?statement|"
    r"bid[_\-\s]?form|auction[_\-\s]?calen|organogram|"
    r"effects[_\-\s]?of[_\-\s]?regional|cross[_\-\s]?listing|"
    r"programme[_\-\s]?manager|opening[_\-\s]?remarks|consultative[_\-\s]?workshop)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"("
    r"KINGDOM OF LESOTHO|LESOTHO|"
    r"AN ACT\b|A BILL\b|BE IT ENACTED|"
    r"Short title|This Act may be cited|These regulations may|"
    r"OFFICIAL GAZETTE|GOVERNMENT GAZETTE|"
    r"Legal Notice|L\.N\.\s*\d|Statutory Instrument|S\.I\.\s*\d|"
    r"CONSTITUTION OF LESOTHO|CONSTITUTION OF THE KINGDOM|"
    r"ARRANGEMENT OF SECTIONS|ARRANGEMENT OF REGULATIONS|"
    r"National Assembly|Senate|Parliament of Lesotho|"
    r"Date of Assent|I assent|His Majesty|"
    r"PENAL CODE|CRIMINAL PROCEDURE|High Court|Court of Appeal"
    r")",
    re.I,
)
ACT_TEXT_RE = re.compile(
    r"(?i)(?:BE IT ENACTED|ARRANGEMENT OF (?:SECTIONS|REGULATIONS)|"
    r"LEGAL NOTICE|STATUTORY INSTRUMENTS?|"
    r"This Act may be cited|These regulations may|"
    r"CONSTITUTION OF (?:LESOTHO|THE KINGDOM)|"
    r"\bAN ACT\b|Act No\.|"
    r"Government Gazette)",
)
ACT_URL_RE = re.compile(
    r"(?i)(?:act[_\s.-]?no|_act\.pdf|act\.pdf|/acts?/|"
    r"regulation|legal.?notice|constitution|gazette|"
    r"statutory|/legislation/|/images/Legislation|"
    r"bill.?no|_bill\.pdf)",
)
JUNK_RE = re.compile(
    r"(?i)\bmpc\b|monetary.?policy.?committee|monetary.?policy.?statement|"
    r"bid.?form|auction.?calen|organogram|annual.?report|"
    r"effects.?of.?regional|cross.?listing|programme.?manager|"
    r"opening.?remarks|consultative.?workshop|budget.?speech|"
    r"press.?release|vacancy|newsletter|strategic.?plan|"
    r"lgcse|schoolsperformance|tip.?report|eom.?lso|"
    r"hand.?over.?report|digital.?transformation.?strategy|"
    r"social.?protection.?strategy|esmp|cerc",
)

LIVE_PAGES = (
    "https://www.gov.ls/",
    "https://www.gov.ls/documents/",
    "https://www.gov.ls/legislation/",
    "https://www.gov.ls/laws/",
    "https://gov.ls/",
    "https://www.parliament.gov.ls/",
    "https://parliament.gov.ls/",
    "https://www.parliament.gov.ls/bills/",
    "https://www.parliament.gov.ls/acts/",
    "https://www.parliament.gov.ls/documents/",
    "https://www.parliament.gov.ls/legislation/",
    "https://nationalassembly.gov.ls/",
    "https://www.nationalassembly.gov.ls/",
    "https://www.nationalassembly.gov.ls/bills/",
    "https://www.nationalassembly.gov.ls/acts/",
    "https://www.judiciary.gov.ls/",
    "https://judiciary.gov.ls/",
    "https://www.judiciary.gov.ls/legislation/",
    "https://www.judiciary.gov.ls/laws/",
    "https://www.judiciary.gov.ls/documents/",
    "https://www.law.gov.ls/",
    "https://law.gov.ls/",
    "https://www.ag.gov.ls/",
    "https://ag.gov.ls/",
    "https://www.justice.gov.ls/",
    "https://justice.gov.ls/",
    "https://www.senate.gov.ls/",
    "https://senate.gov.ls/",
    "https://www.finance.gov.ls/",
    "https://finance.gov.ls/",
    "https://www.centralbank.org.ls/",
    "https://www.centralbank.org.ls/legislation/",
    "https://centralbank.org.ls/legislation/",
    "https://www.centralbank.org.ls/images/Legislation/",
    "https://centralbank.org.ls/images/Legislation/",
)

WP_BASES = (
    "https://www.gov.ls",
    "https://www.parliament.gov.ls",
    "https://www.nationalassembly.gov.ls",
    "https://www.judiciary.gov.ls",
    "https://www.law.gov.ls",
    "https://www.ag.gov.ls",
    "https://www.justice.gov.ls",
    "https://www.senate.gov.ls",
    "https://www.finance.gov.ls",
    "https://www.centralbank.org.ls",
)

CDX_PREFIXES = (
    "www.gov.ls/documents/",
    "www.gov.ls/wp-content/documents/",
    "gov.ls/documents/",
    "www.parliament.gov.ls/",
    "parliament.gov.ls/",
    "www.nationalassembly.gov.ls/",
    "nationalassembly.gov.ls/",
    "www.judiciary.gov.ls/",
    "judiciary.gov.ls/",
    "www.judiciary.gov.ls/wp-content/",
    "www.law.gov.ls/",
    "law.gov.ls/",
    "www.ag.gov.ls/",
    "ag.gov.ls/",
    "www.justice.gov.ls/",
    "justice.gov.ls/",
    "www.senate.gov.ls/",
    "senate.gov.ls/",
    "www.finance.gov.ls/",
    "finance.gov.ls/",
    "www.centralbank.org.ls/legislation/",
    "centralbank.org.ls/legislation/",
    "www.centralbank.org.ls/images/Legislation/",
    "centralbank.org.ls/images/Legislation/",
    "www.centralbank.org.ls/Legislation/",
)

# High-value seeds (official hosts only) — constitution / principal Acts
SEED_URLS = (
    "https://www.judiciary.gov.ls/wp-content/uploads/2022/07/the_constitution_of_lesotho_1993.pdf",
    "https://www.judiciary.gov.ls/wp-content/uploads/2022/07/lesotho_defence_force_act_1996.pdf",
    "https://www.gov.ls/documents/Lesotho_Constitution.pdf",
    "https://www.gov.ls/documents/legal/Tourism_National_Heritage_Bill.pdf",
    "https://www.centralbank.org.ls/legislation/CBL_Act_2000.pdf",
    "https://www.centralbank.org.ls/legislation/CBL_Act_No7_1993.pdf",
    "https://www.centralbank.org.ls/legislation/COMPANIES_ACT_A.pdf",
    "https://www.centralbank.org.ls/legislation/COMPANIES_ACT_B.pdf",
    "https://www.centralbank.org.ls/legislation/COMPANIES_ACT_C.pdf",
    "https://www.centralbank.org.ls/legislation/CREDIT_REPORTING_ACT_2011.pdf",
    "https://centralbank.org.ls/images/Legislation/Principal/CBL_Act_2000.pdf",
    "https://centralbank.org.ls/images/Legislation/NPS/Payment-Systems-Act-2014.pdf",
    "https://centralbank.org.ls/images/Legislation/Financial_Institutions/Financial_Institutions_Act_2012_I.pdf",
    "https://centralbank.org.ls/images/Legislation/Financial_Institutions/Financial_Institutions_Act_2012_II.pdf",
    "https://centralbank.org.ls/images/Legislation/Financial_Institutions/Financial_Institutions_Act_2012_III.pdf",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if not host or BLOCK_HOST.search(host):
        return False
    if host in ALLOWED_EXACT:
        return True
    if host.endswith(".gov.ls") or host == "gov.ls":
        return True
    if host.endswith(".org.ls") and "centralbank" in host:
        return True
    return any(host == s or host.endswith("." + s) for s in ALLOWED_SUFFIXES)


def _norm_url(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    if url.startswith("https://") and ":80/" in url:
        url = url.replace(":80/", "/")
    if "web.archive.org/web/" in url:
        m = re.search(r"https?://web\.archive\.org/web/\d+(?:id_)?/(https?://.*)", url)
        if m:
            url = _norm_url(m.group(1))
    return url


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _ident_from_url(url: str) -> str:
    host = (urlsplit(url).hostname or "ls").lower().replace("www.", "")
    stem = Path(unquote(urlsplit(url).path)).stem
    stem = re.sub(r"[^\w\-]+", "-", stem).strip("-").lower()
    pfx = host.split(".")[0]
    if pfx in ("gov", "www"):
        pfx = "gov"
    return f"{pfx}-{stem}"[:160]


def _priority(name: str) -> int:
    low = name.lower()
    if re.search(r"constitut", low):
        return 0
    if re.search(r"penal.?code|civil.?code|criminal.?procedure", low):
        return 1
    if re.search(r"(parliament|nationalassembly|judiciary|law\.gov|senate)", low):
        if re.search(r"act|bill|constitution", low):
            return 1
    if re.search(r"(^|[/_\-])act|amendment.?act|companies.?act|cbl.?act", low):
        return 2
    if re.search(r"\bbill\b", low):
        return 4
    if re.search(r"regulation|statutory|\bsi[_\-\s]?\d|s\.i|legal.?notice|\bln[_\-\s]?\d", low):
        return 6
    if re.search(r"/legislation/|/images/legislation", low):
        return 7
    if re.search(r"gazette", low):
        return 10
    if "centralbank" in low and re.search(r"mpc|statement|report", low):
        return 40
    return 20


def _should_keep(url: str, title: str = "") -> bool:
    blob = unquote(url) + " " + (title or "")
    if not _host_ok(url):
        return False
    if DROP_RE.search(blob):
        if not re.search(
            r"(?i)(/act[-_ ]|\bact[-_ ]|amendment.?act|constitution|"
            r"penal.?code|civil.?code|/si[-_ ]|\bsi[-_ ]?\d|statutory|"
            r"official.?gazette|legal.?notice|bill.?no|/legislation/)",
            blob,
        ):
            return False
        if re.search(
            r"(?i)(party.?constitution|press.?release|statistical.?report|"
            r"strategic.?plan|annual.?report|poster|leaflet|"
            r"\bmpc\b|monetary.?policy.?statement|bid.?form)",
            blob,
        ):
            return False
    host = (urlsplit(url).hostname or "").lower()
    if "parliament" in host or "nationalassembly" in host or "senate" in host:
        if re.search(r"(?i)(act|bill|si|s\.i|gazette|legal.?notice|constitution)", blob):
            return True
    if "judiciary" in host and re.search(r"(?i)(constitution|code|act|rules|procedure)", blob):
        return True
    return bool(KEEP_RE.search(blob))


def prefer_enacting_body(text: str) -> str:
    """Skip arrangement/TOC so article split targets operative sections."""
    if not text:
        return text
    m = re.search(r"(?is)BE IT ENACTED[^\n]*\n", text)
    if m and m.end() < len(text) - 200:
        return text[m.end() :]
    # Operative s.1 (not TOC "1. Short title." / "1. Citation and commencement")
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


def split_ls_articles(text: str, rid: str, source_url: str, date=None) -> list:
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


def save_ls_instrument(
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
    docs = split_ls_articles(text, rid, source_url, None)
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
        collector="collect_ls.py",
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
            r"CONSTITUTION OF|Government Gazette",
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
        docs = split_ls_articles(text, rid, url, date)
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
        meta["article_reprocess"] = "collect_ls.py-commonwealth-sections"
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
        url = _norm_url(url)
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

    for seed in SEED_URLS:
        add(seed, title=Path(unquote(urlsplit(seed).path)).stem)

    for page in LIVE_PAGES:
        for href, title in _scrape_page_pdfs(page):
            add(href, title=title)
        time.sleep(0.1)

    for base in WP_BASES:
        for page in range(1, 5):
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
                hits = (
                    cdx_urls(
                        prefix,
                        limit=env_int("CDX_LIMIT", 120),
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
                stem = Path(unquote(urlsplit(orig).path)).stem
                add(orig, title=stem, ts=ts, size_hint=length or None)

    items.sort(key=lambda x: (x[0], x[1]))
    log.info(
        "catalog %s (pri0=%s pri1-2=%s)",
        len(items),
        sum(1 for p, *_ in items if p == 0),
        sum(1 for p, *_ in items if 1 <= p <= 2),
    )
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 60)
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
    for p in (ROOT / CC / "instruments").glob("*.json"):
        try:
            u = _norm_url(json.loads(p.read_text(encoding="utf-8")).get("source_url") or "")
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
        nu = _norm_url(url).lower()
        if rid in done or nu in have_urls:
            skip += 1
            continue
        if size_hint and size_hint > MAX_PDF_BYTES:
            skip += 1
            continue
        # after enough dense Acts, skip low-priority noise
        if pri >= 20 and ok >= max(10, max_new // 3):
            skip += 1
            continue
        got = fetch_official(url, ua=UA, wayback=True, wayback_ts=ts)
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
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_too_large"})
            continue
        use_title = title or first_title(text, ident)
        blob = f"{ident}|{use_title}|{url}|{text[:2500]}"
        if JUNK_RE.search(blob) and not ACT_TEXT_RE.search(blob):
            skip += 1
            log.info("skip junk post-fetch %s", ident[:60])
            continue
        if not TEXT_KEEP_RE.search(text[:12000]) and not ACT_TEXT_RE.search(blob):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_not_legal"})
            continue
        for line in text.splitlines():
            if len(line.strip()) > 18:
                use_title = line.strip()[:240]
                break
        if save_ls_instrument(
            ident=ident,
            title=use_title,
            text=text,
            source_url=_norm_url(url),
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
            log.info("ok pri=%s %s method=%s chars=%s", pri, ident[:60], got.get("method"), len(text))
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
            "Lesotho official *.gov.ls (gov / parliament / nationalassembly / "
            "judiciary / law / ag / justice / senate / finance) + centralbank.org.ls"
        ),
        source_urls=[
            "https://www.gov.ls/",
            "https://www.parliament.gov.ls/",
            "https://nationalassembly.gov.ls/",
            "https://www.judiciary.gov.ls/",
            "https://www.law.gov.ls/",
            "https://www.ag.gov.ls/",
            "https://www.justice.gov.ls/",
            "https://www.senate.gov.ls/",
            "https://www.finance.gov.ls/",
            "https://www.centralbank.org.ls/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (*.gov.ls + centralbank legislation live+CDX; "
            "commonwealth section densify; PDFs >12MB skipped; LesothoLII/AfricanLII excluded)"
        ),
        notes=(
            f"Official *.gov.ls / centralbank.org.ls only. Commonwealth 1. section split + "
            f"enacting-body prefer. instruments={n_inst} articles={arts}. "
            "NOT LesothoLII / AfricanLII. No WAF bypass. Not legal advice. ls=Lesotho (not ug/sz/sd)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s instruments=%s articles=%s", ok, skip, fail, n_inst, arts)


if __name__ == "__main__":
    main()
