#!/usr/bin/env python3
"""Saint Vincent and the Grenadines: legal.gov.vc Official Gazette + gov.vc Acts.

Official-only *.gov.vc. Ministry of Legal Affairs Official Gazette PDFs
(legal.gov.vc) + Constitution / Acts on www.gov.vc + CDX of the same official
URLs. Not vLex / commercial aggregators.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import logging, os, re, sys, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id
from pdf_extract_lib import extract_pdf_text
import requests

CC, COUNTRY, LANG = "vc", "Saint Vincent and the Grenadines", "en"
SOURCE_TYPE = "legal_gov_vc"
LICENSE = (
    "Government of Saint Vincent and the Grenadines — Official Gazette / Laws "
    "(legal.gov.vc Ministry of Legal Affairs and Justice; www.gov.vc; "
    "assembly.gov.vc House of Assembly). "
    "Authentic Official Gazette / Government Printer text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://legal.gov.vc/legal/)"
)
# Commonwealth Cap / Constitution / Civil Service Orders drafting.
# Broad for Acts/Caps/SROs; ART_NARROW for gazette shells (no list-item false sections).
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule)\s+[0-9]+[A-Za-z]?\b|"
    r"s\.\s*[0-9]+[A-Za-z]?\b|"
    r"[0-9]+[A-Za-z]?\.\s+\([0-9]+[a-z]?\)|"
    r"[0-9]+[A-Za-z]?\.\s+[A-Z](?:[A-Za-z'\-/ ,]{1,90})|"
    r"[0-9]+\.[0-9]+[A-Za-z]?\b)"
)
ART_NARROW = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?)\b"
)
log = logging.getLogger("vc")
MAX_PDF = env_int("MAX_PDF_BYTES", 10 * 1024 * 1024)

HOST_OK = (
    "legal.gov.vc",
    "gov.vc",
    "assembly.gov.vc",
    "finance.gov.vc",
)
SKIP_RE = re.compile(
    r"(powerpoint|pptx|agenda|newsletter|brochure|order.?of.?the.?day|"
    r"order.?pa+er|house.?of.?assembly.?order|"
    r"minutes|hansard|favicon|holder__|budget.?address|budget.?speech|"
    r"budget.?estimates|weather.?report|passport.?form|"
    r"vacancy|tender|questionnaire|communiqu|"
    r"census|facilitator|early.?childhood.?constitution|entry.?visa|visa.?application|visa.?criteria|visa.?form|"
    r"flyer|conch|turtle|spearfishing|"
    r"\bbill\b|draft-|draft_|draft\s|final.?draft|"
    r"policy(?!.*act)|action.?plan|strategy|"
    r"nbsap|energy.?action|ict.?strategy|"
    r"\.docx?$|\.jpe?g$|\.png$|\.doc$)",
    re.I,
)
KEEP_RE = re.compile(
    r"(gazette|act|acts|constitution|cap|chapter|statutory|instrument|"
    r"s[_ ]?r[_ ]?&?o|sro|regulation|order|rules?|proclamation|"
    r"/PDF/|/PoliciesActsAndBills/|/visitors/|contentmanager/articlefiles|"
    r"economic.?substance|import.?and.?export|wages.?regulation|"
    r"recruiting.?of.?workers|fixed.?penalty|"
    r"extraordinary|extra-?ordinary|assented)",
    re.I,
)
CDX_PREFIXES = (
    "legal.gov.vc/legal/images/PDF/",
    "www.legal.gov.vc/legal/images/PDF/",
    "www.gov.vc/images/PoliciesActsAndBills/",
    "gov.vc/images/PoliciesActsAndBills/",
    "www.gov.vc/images/visitors/",
    "www.gov.vc/images/Bankruptcy",
    "www.gov.vc/images/pdf_documents/SRO",
    "www.gov.vc/images/VacanciesAndNotices/Economic-Substance",
    # contentmanager CDX too noisy (Order Papers); use SEED_DOCS for known SROs
    "www.gov.vc/foreign/images/stories/Foreign_Affairs/",
    "assembly.gov.vc/assembly/images/PDF/proclamation/",
)
# Gazette year shelves on legal.gov.vc (Joomla category ids)
GAZETTE_PAGES = (
    (2026, "62-2026-gazettes"),
    (2025, "51-publications"),
    (2024, "53-2024-gazettes"),
    (2023, "54-2023-gazettes"),
    (2022, "55-2022-gazettes"),
    (2021, "56-2021gazettes"),
    (2020, "57-2020-gazettes"),
    (2019, "58-2019-gazettes"),
    (2018, "59-2018-gazettes"),
    (2017, "60-2017-gazettes"),
    (2016, "61-2016-gazettes"),
)
SEED_DOCS = (
    (
        "https://www.gov.vc/images/visitors/1979_constitution.pdf",
        "Constitution of Saint Vincent and the Grenadines 1979",
        "CONSTITUTION",
    ),
    (
        "https://www.gov.vc/images/PoliciesActsAndBills/SVG_Freedom_of_Information_Act_2003.pdf",
        "Freedom of Information Act 2003",
        "ACT",
    ),
    (
        "https://www.gov.vc/images/PoliciesActsAndBills/SVG_Cybercrime_Act_2016.pdf",
        "Cybercrime Act 2016",
        "ACT",
    ),
    (
        "https://www.gov.vc/images/PoliciesActsAndBills/SVG_Electronic_Transactions_Act_2015.pdf",
        "Electronic Transactions Act 2015",
        "ACT",
    ),
    (
        "https://www.gov.vc/images/PoliciesActsAndBills/Public-Order-Act.pdf",
        "Public Order Act",
        "ACT",
    ),
    (
        "https://www.gov.vc/images/PoliciesActsAndBills/The_Permitted_Use_of_Cannabis_for_Religious_Purposes_Act_ACT_of-2018.pdf",
        "Permitted Use of Cannabis for Religious Purposes Act 2018",
        "ACT",
    ),
    (
        "https://www.gov.vc/images/Bankruptcy-and-Insolvency-Regulations-2015-PART-1-of-3.PDF",
        "Bankruptcy and Insolvency Regulations 2015 Part 1",
        "SRO",
    ),
    (
        "https://assembly.gov.vc/assembly/images/PDF/proclamation/Proclamation.PDF",
        "Proclamation (House of Assembly)",
        "PROCLAMATION",
    ),
    (
        "https://www.gov.vc/images/pdf_documents/SRO---Public-Health-Fixed-Penalty-Rules-2021.pdf",
        "Public Health Fixed Penalty Rules 2021",
        "SRO",
    ),
    (
        "https://www.gov.vc/images/VacanciesAndNotices/Economic-Substance-Regulations-2021-.pdf",
        "Economic Substance Regulations 2021",
        "SRO",
    ),
    (
        "https://www.gov.vc/foreign/images/stories/Foreign_Affairs/import%20and%20export%20control%20regulations.pdf",
        "Import and Export Control Regulations",
        "SRO",
    ),
    (
        "http://www.gov.vc/contentmanager/articlefiles/2611-STATUTORY%20RULES%20AND%20ORDERS%20No%2015.pdf",
        "Statutory Rules and Orders No 15",
        "SRO",
    ),
    (
        "http://www.gov.vc/contentmanager/articlefiles/2611-Statutory%20Rules%20and%20Orders%20No%2016.pdf",
        "Statutory Rules and Orders No 16",
        "SRO",
    ),
    (
        "http://www.gov.vc/contentmanager/articlefiles/2611-Wages%20Regulation%20_Port%20Workers_%20Order%20Booklet%2010.pdf",
        "Wages Regulation Port Workers Order",
        "SRO",
    ),
    (
        "http://www.gov.vc/contentmanager/articlefiles/2611-Recruiting%20of%20Workers%20Regulations.pdf",
        "Recruiting of Workers Regulations",
        "SRO",
    ),
)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if "?" in url and ".pdf" in url.lower():
        url = url.split("?")[0]
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("gov.vc"):
        url = url.replace("http://", "https://").replace(":80/", "/")
        # drop accidental www on legal
        if host == "www.legal.gov.vc":
            url = url.replace("://www.", "://", 1)
    return url


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK)


def _category(url: str, hint: str = "") -> str:
    blob = f"{url} {hint}".lower()
    if "constitution" in blob:
        return "CONSTITUTION"
    if re.search(r"\bact\b|/PoliciesActsAndBills/.*act", blob) and "bill" not in blob:
        if re.search(r"statutory|regulation|order|sro|s\.?r", blob) and "act" not in Path(
            urlparse(url).path
        ).stem.lower():
            pass
        else:
            return "ACT"
    if re.search(
        r"statutory|s[_ ]?r[_ ]?&?o|\bsro\b|regulation|persons.?abroad|"
        r"price.?control|public.?health",
        blob,
    ):
        return "SRO"
    if "proclamation" in blob:
        return "PROCLAMATION"
    if re.search(r"extra-?ordinary|extraordinary|etxra", blob):
        return "EXTRAORDINARY"
    if "gazette" in blob or "/PDF/" in url or "Gazettes" in url:
        return "GAZETTE"
    if re.search(r"regulation|order|rules?", blob):
        return "SRO"
    return ""


def _ident_from_url(url: str, hint: str = "") -> str:
    if hint:
        stem = re.sub(r"[^\w.\-]+", "_", hint).strip("_")[:160]
        if stem and len(stem) > 6:
            return stem
    path = unquote(urlparse(url).path)
    stem = Path(path).stem[:160] or "doc"
    return stem[:160]


def _rank(ident: str, cat: str, url: str) -> int:
    """Prefer Constitution / Cap Acts / substantive SROs over Extraordinary Gazette shells."""
    blob = f"{ident} {cat} {url}".lower()
    if cat == "CONSTITUTION" or "constitution" in blob:
        return 0
    if re.search(r"\bcap\b|chapter\s*\d+|PoliciesActsAndBills", blob) and "bill" not in blob:
        return 1
    if cat == "ACT" or (re.search(r"\bact\b", blob) and "bill" not in blob):
        return 2
    if cat == "SRO" or re.search(r"statutory|regulation|sro|s[_ ]?r|civil.?service.?order", blob):
        return 3
    if cat == "PROCLAMATION" or "proclamation" in blob:
        return 4
    # Extraordinary Gazette issue shells are last-resort (poor section splits)
    if cat == "EXTRAORDINARY" or re.search(r"extra-?ordin", blob):
        return 8
    if cat == "GAZETTE" or "gazette" in blob:
        return 7
    return 6


def discover():
    items, seen_url, best = [], set(), {}

    def add(url, ts="", title_hint="", cat=""):
        url = _norm(url)
        low = url.lower()
        if ".pdf" not in low:
            return
        if not _host_ok(url):
            return
        blob = f"{low} {title_hint} {cat}"
        if SKIP_RE.search(blob):
            return
        if not KEEP_RE.search(blob):
            return
        cat = cat or _category(url, title_hint)
        ident = _ident_from_url(url, title_hint)
        if url in seen_url:
            return
        seen_url.add(url)
        row = (ident, url, (title_hint or "").strip()[:200], cat, ts or "")
        prev = best.get(ident)
        if prev is None or _rank(row[0], row[3], row[1]) < _rank(prev[0], prev[3], prev[1]):
            best[ident] = row
        elif _rank(row[0], row[3], row[1]) == _rank(prev[0], prev[3], prev[1]):
            if (ts or "") > (prev[4] or ""):
                best[ident] = row

    for url, hint, cat in SEED_DOCS:
        add(url, "", hint, cat)

    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    sess.headers["Accept"] = "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8"
    sess.verify = False
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    # --- Official Gazette year shelves (primary) ---
    for year, slug in GAZETTE_PAGES:
        page = f"https://legal.gov.vc/legal/index.php/publications/{slug}"
        try:
            gr = sess.get(page, timeout=45)
            if gr.status_code != 200:
                log.warning("gazette year %s status=%s", year, gr.status_code)
                continue
            before = len(best)
            for m in re.finditer(
                r'href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>(.*?)</a>',
                gr.text,
                re.I | re.S,
            ):
                href = m.group(1)
                tip = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                tip = re.sub(r"\s+", " ", tip)
                if tip.lower() in ("download", "view", "pdf", ""):
                    tip = Path(unquote(urlparse(href).path)).stem.replace("_", " ")
                full = urljoin(gr.url, href)
                cat = _category(full, tip)
                add(full, "", tip[:200], cat)
            # bare PDF hrefs without useful inner text
            for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', gr.text, re.I):
                full = urljoin(gr.url, href)
                tip = Path(unquote(urlparse(full).path)).stem.replace("_", " ").replace("-", " ")
                add(full, "", tip[:200], _category(full, tip))
            log.info("gazette %s +%s catalog=%s", year, len(best) - before, len(best))
        except Exception as exc:
            log.warning("gazette year %s fail: %s", year, exc)

    # --- PoliciesActsAndBills shelf (gov.vc) via known seeds + homepage links ---
    try:
        home = sess.get("https://www.gov.vc/", timeout=40)
        if home.status_code == 200:
            for href in re.findall(
                r'href=["\']([^"\']+(?:PoliciesActsAndBills|visitors)[^"\']+\.pdf[^"\']*)["\']',
                home.text,
                re.I,
            ):
                full = urljoin(home.url, href)
                tip = Path(unquote(urlparse(full).path)).stem.replace("_", " ")
                add(full, "", tip[:200], _category(full, tip))
    except Exception as exc:
        log.warning("gov.vc home fail: %s", exc)

    # --- CDX of official PDF endpoints ---
    lim = env_int("CDX_LIMIT", 1500)
    for prefix in CDX_PREFIXES:
        try:
            for h in cdx_urls(
                prefix,
                limit=lim,
                match_type="prefix",
                extra_filters=["mimetype:application/pdf"],
            ):
                orig = h.get("original") or ""
                ts = h.get("timestamp") or ""
                if orig:
                    tip = Path(unquote(urlparse(orig).path)).stem.replace("_", " ")[:200]
                    add(orig, ts, tip)
        except Exception as exc:
            log.warning("cdx %s fail: %s", prefix, exc)

    items = list(best.values())
    items.sort(key=lambda it: (_rank(it[0], it[3], it[1]), it[1]))
    log.info("catalog %s", len(items))
    return items


def ocr_pdf(raw: bytes) -> tuple[str, str, int]:
    os.environ.setdefault("TESSDATA_PREFIX", "/home/box/tessdata")
    ocr_pages = env_int("OCR_PAGES", 10)
    return extract_pdf_text(raw, enable_ocr=True, ocr_lang="eng", ocr_max_pages=ocr_pages)


def fetch_pdf(url: str, wayback_ts: str = "") -> dict:
    got = fetch_official(
        url, ua=UA, verify=False, min_text=120, wayback_ts=wayback_ts or None
    )
    if got.get("status") == "success":
        return got
    raw = got.get("content") or b""
    if isinstance(raw, bytes) and raw[:4] == b"%PDF" and len(raw) <= MAX_PDF:
        text, how, pages = ocr_pdf(raw)
        if text and len(text) >= 100:
            got.update(status="success", text=text, method=f"ocr:{how}", error="")
            return got
        got["error"] = (got.get("error") or "") + f";ocr_failed:{how}"
    return got


def reprocess_existing() -> int:
    """Re-split articles on saved instruments with current ART (no re-fetch)."""
    from common import ROOT
    import json
    n = 0
    for path in sorted((ROOT / CC / "instruments").glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if len(text) < 80:
            continue
        rid = rec.get("id") or path.stem
        cat = ((rec.get("metadata") or {}).get("category") or "")
        use_re = ART if cat in ("ACT", "CONSTITUTION", "SRO", "CAP") else ART_NARROW
        docs = __import__("world_lib", fromlist=["split_custom"]).split_custom(
            text, rid, rec.get("source_url") or "", rec.get("date"), use_re
        )
        old = int(rec.get("article_count") or 0)
        if len(docs) == old and old > 0:
            continue
        # Prefer material densification; still rewrite when improved
        if len(docs) < old and old >= 2 and len(docs) < 2:
            continue
        rec["documents"] = docs
        rec["article_count"] = len(docs)
        rec["article_extraction_status"] = "ok" if len(docs) >= 2 else ("missing" if not docs else "partial")
        meta = rec.get("metadata") or {}
        meta["article_re"] = "vc_cap_constitution_orders_v2"
        rec["metadata"] = meta
        # Direct write to avoid index.jsonl append bloat on reprocess
        from common import atomic_write
        body = json.dumps(rec, ensure_ascii=False, indent=2) + "\n"
        atomic_write(path, body)
        n += 1
        log.info("reprocess %s arts %s->%s", rid[:70], old, len(docs))
    return n


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 150)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = ocr_used = 0
    if os.environ.get("REPROCESS_EXISTING", "1") not in ("0", "false", "False"):
        rp = reprocess_existing()
        log.info("reprocessed %s instruments", rp)
    for ident, url, hint, cat, ts in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_pdf(url, ts)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if "ocr" in str(got.get("method") or "").lower():
            ocr_used += 1
        title = hint or None
        if not title:
            for line in text.splitlines():
                if len(line.strip()) > 18:
                    title = line.strip()[:240]
                    break
        if cat and title and cat.lower() not in title.lower():
            title = f"{title} [{cat}]"
        use_re = ART if cat in ("ACT", "CONSTITUTION", "SRO", "CAP") else ART_NARROW
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_vc.py",
            article_re=use_re,
            extra_meta={"fetch_method": got.get("method"), "category": cat, "wayback_ts": ts},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Saint Vincent and the Grenadines Official Gazette (legal.gov.vc) / gov.vc Acts",
        source_urls=[
            "https://legal.gov.vc/legal/",
            "https://legal.gov.vc/legal/index.php/publications",
            "https://legal.gov.vc/legal/index.php/publications/62-2026-gazettes",
            "https://www.gov.vc/images/visitors/1979_constitution.pdf",
            "https://www.gov.vc/images/PoliciesActsAndBills/",
            "https://assembly.gov.vc/assembly/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (legal.gov.vc Official Gazette 2016–2026 + "
            "gov.vc Constitution/Acts + CDX)"
        ),
        notes=(
            f"Official legal.gov.vc Gazette PDFs (Acts/S.R.&O. published in Gazette) + "
            f"www.gov.vc Constitution 1979 + PoliciesActsAndBills Acts + assembly proclamations; "
            f"live-first + Wayback CDX. Prefer Constitution + Cap/Acts + SROs over Extraordinary Gazette shells; Cap/Order article_re densify. "
            f"OCR used={ocr_used}. Skip bills/drafts/policies. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s ocr=%s", ok, skip, fail, ocr_used)


if __name__ == "__main__":
    main()
