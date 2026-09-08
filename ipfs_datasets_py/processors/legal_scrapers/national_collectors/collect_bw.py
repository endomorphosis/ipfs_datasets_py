#!/usr/bin/env python3
"""Botswana: official Acts / Bills / Gazette / SI PDFs from government portals.

Primary: gov.bw, parliament.gov.bw / botswanaspeaks.gov.bw (Parliament Bills &
Extraordinary Gazettes), BURS tax Acts, Attorney-General-linked portal PDFs,
and statutory agency hosts that publish official Acts/Regulations/SIs
(Bank of Botswana, BOCRA, BERA, CAAB, NBFIRA, PPADB, Competition Authority,
HRDC, justice.gov.bw).

Skips: botswanalaws.com, SAFLII, laws.co.bw (private), drafts, order/notice
papers, press releases. elaws.gov.bw is preferred by gov.bw but unreachable
from this collector environment (recorded as a coverage gap).
Live official URL first; Wayback of the same official URL on failure.
No WAF bypass.
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "bw", "Botswana", "en"
SOURCE_TYPE = "botswana_official_gazettes_acts"
LICENSE = (
    "Laws / Bills / Gazette instruments of Botswana as published on official "
    "government and statutory-agency portals (gov.bw, parliament.gov.bw, "
    "botswanaspeaks.gov.bw, burs.org.bw, and related .gov.bw / statutory hosts). "
    "Authentic Government Printer / e-Laws text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.gov.bw/)"
ART = re.compile(
    r"(?im)^\s*((?:Section|Sec\.|Article|Art\.|Regulation|Reg\.)\s+\d+[A-Za-z]?\.?)\b"
)
log = logging.getLogger("bw")

BLOCK_HOST = re.compile(
    r"(botswanalaws\.com|saflii\.org|laws\.co\.bw|gazettes\.africa|"
    r"africanlii\.org|commonlii\.org|ulii\.org)",
    re.I,
)
SKIP_NAME = re.compile(
    r"(draft|press[_\-\s]?release|order[_\-\s]?paper|notice[_\-\s]?paper|"
    r"ordpap|notpap|fact[_\-\s]?sheet|brochure|application[_\-\s]?form|"
    r"form[_\-\s]?ita|tin[_\-\s]?application|action[_\-\s]?plan|"
    r"bill[_\-\s]?shock|committee[_\-\s]?of[_\-\s]?supply|speech|"
    r"statement|monetary[_\-\s]?policy|financial[_\-\s]?position|"
    r"business[_\-\s]?expectations|external[_\-\s]?sector|"
    r"data[_\-\s]?protection[_\-\s]?and[_\-\s]?privacy[_\-\s]?statement|"
    r"privacy[_\-\s]?statement|manual[_\-\s]?of[_\-\s]?operating|"
    r"roll[_\-\s]?out|schedule[_\-\s]?roll|contacts?\.pdf|"
    r"advert|newsletter|vacancy|tender|annual[_\-\s]?report|"
    r"abstract|fruit[_\-\s]?ninja|leather[_\-\s]?and[_\-\s]?leather|"
    r"manufacturers[_\-\s]?directory|call[_\-\s]?for[_\-\s]?research|"
    r"audit[_\-\s]?of[_\-\s]?billing|broadcaster.?s[_\-\s]?code|"
    r"interactive\.pdf|corrigendum[_\-\s]?-[_\-\s]?ordpap|"
    r"addendum[_\-\s]?-[_\-\s]?ordpap|addendum[_\-\s]?-[_\-\s]?notpap|"
    r"winter[_\-\s]?session|parliament[_\-\s]?business[_\-\s]?update)",
    re.I,
)
LAWISH_NAME = re.compile(
    r"("
    r"\bact\b|_act_|-act-|act\.pdf|act%20|"
    r"\bbill\b|_bill_|-bill-|bill\.pdf|"
    r"regulation|regulations|"
    r"gazette|statutory[_\-\s]?instrument|\bsi[_\-\s]?\d|"
    r"chapter[_\-\s]?\d|cap[_\-\s\.]?\d|"
    r"enacted|supplement[_\-\s]?[abc]\b"
    r")",
    re.I,
)
LAW_MARK = re.compile(
    r"(ENACTED by the Parliament of Botswana|AN ACT\b|A BILL\b|"
    r"Short title|This Act may be cited|GOVERNMENT GAZETTE|"
    r"ARRANGEMENT OF SECTIONS|Statutory Instrument|supplement [ABC]\b|"
    r"Date of Assent|No\.\s*\d+\s+of\s+20\d{2})",
    re.I,
)

CDX_PREFIXES = [
    "www.gov.bw/sites/default/files/",
    "gov.bw/sites/default/files/",
    "botswanaspeaks.gov.bw/media/BILLS/",
    "www.botswanaspeaks.gov.bw/media/BILLS/",
    "www.burs.org.bw/",
    "www.bankofbotswana.bw/assets/",
    "www.bocra.org.bw/sites/default/files/",
    "www.bera.co.bw/downloads/",
    "www.caab.co.bw/wp-content/uploads/",
    "www.nbfira.org.bw/sites/default/files/",
    "www.ppadb.co.bw/Act_Reg/",
    "www.competitionauthority.co.bw/sites/default/files/",
    "www.hrdc.org.bw/sites/default/files/",
    "www.justice.gov.bw/sites/default/files/",
    "www.parliament.gov.bw/documents/",
]

LIVE_SEEDS = [
    "https://www.gov.bw/law-crime-and-justice/access-laws-botswana",
    "https://www.botswanaspeaks.gov.bw/category/4/parliament-business",
    "https://www.burs.org.bw/index.php/tax/tax-laws-2026",
    "https://www.burs.org.bw/index.php/tax/tax-downloads",
    "https://www.bocra.org.bw/legislation",
    "https://www.caab.co.bw/regulations/",
    "https://www.bankofbotswana.bw/",
    "https://www.competitionauthority.co.bw/",
    "https://www.hrdc.org.bw/",
    "https://www.ppadb.co.bw/",
    "https://www.nbfira.org.bw/",
    "https://www.justice.gov.bw/",
    "https://www.parliament.gov.bw/",
]

BURS_ACT_PAGES = [
    "https://www.burs.org.bw/index.php/tax/tax-laws-2026",
    "https://www.burs.org.bw/index.php/tax/tax-downloads",
]


def _norm(url: str) -> str:
    u = (url or "").split("#")[0]
    u = u.replace("http://", "https://")
    u = re.sub(r":80/", "/", u)
    u = re.sub(r"https://gov\.bw/", "https://www.gov.bw/", u)
    u = re.sub(r"https://parliament\.gov\.bw/", "https://www.parliament.gov.bw/", u)
    u = re.sub(r"https://botswanaspeaks\.gov\.bw/", "https://www.botswanaspeaks.gov.bw/", u)
    parts = urlparse(u)
    # Keep only download= query params (BURS phocadownload); drop tracking junk
    q = parts.query or ""
    if "download=" in q:
        m = re.search(r"(download=\d+:[a-z0-9\-]+)", q, re.I)
        q = m.group(1) if m else ""
    else:
        q = ""
    path = quote_path(unquote(parts.path)) if (" " in unquote(parts.path) or "%" in parts.path) else parts.path
    # Prefer percent-encoded spaces for fetch reliability
    if " " in path:
        path = quote_path(path)
    u = parts._replace(path=path, query=q, params="", fragment="").geturl()
    return u.rstrip("?")


def quote_path(path: str) -> str:
    from urllib.parse import quote

    return quote(path, safe="/%")


def _ident_from_url(url: str) -> str:
    path = unquote(urlparse(url.split("?")[0]).path)
    name = Path(path).name
    if "download=" in url:
        m = re.search(r"download=(\d+):([a-z0-9\-]+)", url, re.I)
        if m:
            name = f"{m.group(2)}-{m.group(1)}"
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    name = re.sub(r"\s+", " ", name).strip()
    return re.sub(r"[^\w.\-]+", "-", name)[:160] or "bw-doc"


def _host_ok(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    if BLOCK_HOST.search(url):
        return False
    host = (urlparse(url).hostname or "").lower()
    # official / statutory agency hosts only
    ok_suffixes = (
        ".gov.bw",
        "gov.bw",
        "burs.org.bw",
        "bankofbotswana.bw",
        "bocra.org.bw",
        "bera.co.bw",
        "caab.co.bw",
        "nbfira.org.bw",
        "ppadb.co.bw",
        "competitionauthority.co.bw",
        "hrdc.org.bw",
        "botswanaspeaks.gov.bw",
    )
    return any(host == s or host.endswith("." + s) or host.endswith(s) for s in ok_suffixes)


def _is_law_url(url: str) -> bool:
    u = _norm(url)
    if not _host_ok(u):
        return False
    low = unquote(u).lower()
    if SKIP_NAME.search(low):
        return False
    # BURS phocadownload acts
    if "burs.org.bw" in low and "download=" in low:
        if re.search(r"(act|bill|regulation|gazette|cap[-_ ]?\d|statutory)", low):
            return True
        return False
    if ".pdf" not in low and "download=" not in low:
        return False
    name = unquote(urlparse(u.split("?")[0]).path).split("/")[-1]
    if SKIP_NAME.search(name):
        return False
    # Prefer explicit lawish filenames; allow /BILLS/ folder and Act_Reg/
    if "/bills/" in low or "/act_reg/" in low or "extraordinary" in low and "gazette" in low:
        return not SKIP_NAME.search(name)
    if LAWISH_NAME.search(name) or LAWISH_NAME.search(low):
        return True
    return False


def _title_from_text(text: str, fallback: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in lines[:50]:
        if re.search(r"\b(ACT|BILL|REGULATIONS?|GAZETTE)\b", ln) and 8 <= len(ln) <= 180:
            if not re.match(r"^(TITLE|PREVIOUS|NEXT|CONTENTS)\b", ln, re.I):
                return ln[:240]
    for ln in lines:
        if len(ln) >= 12 and not ln.lower().startswith("just a moment"):
            return ln[:240]
    return fallback[:240]


def _looks_like_law(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    head = text[:8000]
    if LAW_MARK.search(head):
        return True
    # section-dense statutes without classic preamble
    secs = len(re.findall(r"(?im)^\s*Section\s+\d+", text[:20000]))
    return secs >= 5


def _add(items: list, seen: set, url: str, ident: str | None = None) -> None:
    url = _norm(url)
    if not url or url in seen or not _is_law_url(url):
        return
    seen.add(url)
    items.append((ident or _ident_from_url(url), url))


def _harvest_html(url: str) -> list[str]:
    out = []
    try:
        r = live_get(url, ua=UA, verify=False, timeout=(20, 50))
    except Exception as exc:
        log.info("seed fail %s: %s", url[:90], exc)
        return out
    text = r.text or ""
    for href in re.findall(r'href=["\']([^"\']+)["\']', text, re.I):
        full = urljoin(url, href)
        if ".pdf" in full.lower() or "download=" in full.lower():
            out.append(full)
    for m in re.findall(r'(https?://[^"\'\s>]+\.pdf)', text, re.I):
        out.append(m)
    return out


def _botswanaspeaks_bills() -> list[tuple[str, str]]:
    """Crawl Parliament Business articles for Bill / Gazette PDFs only."""
    items, seen_u, seen_a = [], set(), set()
    seeds = ["https://www.botswanaspeaks.gov.bw/category/4/parliament-business"]
    articles = []
    for su in seeds:
        try:
            r = live_get(su, ua=UA, verify=False, timeout=(20, 60))
        except Exception as exc:
            log.info("speaks category fail: %s", exc)
            continue
        for href in re.findall(r'href=["\']([^"\']+)["\']', r.text or "", re.I):
            full = urljoin(su, href).split("#")[0]
            if "/article/" in full and full not in seen_a:
                seen_a.add(full)
                articles.append(full)
    log.info("speaks articles %s", len(articles))
    for au in articles[: env_int("SPEAKS_ARTICLES", 120)]:
        try:
            r = live_get(au, ua=UA, verify=False, timeout=(15, 40))
        except Exception:
            continue
        for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', r.text or "", re.I):
            full = _norm(urljoin(au, href))
            low = unquote(full).lower()
            # only BILLS / gazette paths — skip order/notice papers
            if "/bills/" not in low and "gazette" not in low and "extraordinary" not in low:
                continue
            if full in seen_u:
                continue
            if not _is_law_url(full):
                continue
            seen_u.add(full)
            items.append((_ident_from_url(full), full))
    log.info("speaks bill/gazette pdfs %s", len(items))
    return items


def _burs_downloads() -> list[tuple[str, str]]:
    items, seen = [], set()
    for page in BURS_ACT_PAGES:
        try:
            r = live_get(page, ua=UA, verify=False, timeout=(20, 50))
        except Exception as exc:
            log.info("burs page fail %s: %s", page, exc)
            continue
        for m in re.findall(r"(download=\d+:[a-z0-9\-]+)", r.text or "", re.I):
            slug = m.split(":", 1)[-1]
            if not re.search(r"(act|bill|regulation|gazette|cap-|statutory|order)", slug, re.I):
                continue
            if re.search(r"(form|faq|guidance|guideline|table|certificate|application)", slug, re.I):
                continue
            url = urljoin(page, f"?{m}" if "?" not in page else f"&{m}")
            # Prefer clean absolute download URLs on same path
            if "tax-laws-2026" in page:
                url = f"https://www.burs.org.bw/index.php/tax/tax-laws-2026?{m}"
            elif "tax-downloads" in page:
                url = f"https://www.burs.org.bw/index.php/tax/tax-downloads?{m}"
            else:
                url = urljoin(page.split("?")[0], "?" + m)
            if url in seen:
                continue
            if not _is_law_url(url):
                continue
            seen.add(url)
            items.append((_ident_from_url(url), url))
    log.info("burs act downloads %s", len(items))
    return items


def discover():
    items, seen = [], set()

    # 1) Parliament Bills / Extraordinary Gazettes (botswanaspeaks)
    for ident, url in _botswanaspeaks_bills():
        _add(items, seen, url, ident)

    # 2) BURS official tax Acts
    for ident, url in _burs_downloads():
        _add(items, seen, url, ident)

    # 3) Live seed page PDF harvest
    for su in LIVE_SEEDS:
        for href in _harvest_html(su):
            _add(items, seen, href)

    # 4) CDX of official hosts (Wayback index of live official URLs)
    limit = env_int("CDX_LIMIT", 180)
    for prefix in CDX_PREFIXES:
        for h in cdx_urls(prefix, limit=limit, match_type="prefix", extra_filters=["mimetype:application/pdf"]):
            orig = (h.get("original") or "").replace("http://", "https://")
            _add(items, seen, orig)
        if len(items) >= env_int("CATALOG_CAP", 400):
            break

    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 80)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    for ident, url in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=180)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if not _looks_like_law(text):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "not_law_like"})
            continue
        title = _title_from_text(text, ident)
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
            collector="collect_bw.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s method=%s", ident[:70], len(text), got.get("method"))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Botswana official portals (gov.bw / Parliament / BURS / statutory agencies)",
        source_urls=[
            "https://www.gov.bw/",
            "https://www.parliament.gov.bw/",
            "https://www.botswanaspeaks.gov.bw/",
            "https://www.burs.org.bw/",
            "https://www.elaws.gov.bw/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete; elaws.gov.bw unreachable from collector host",
        notes=(
            "Official Acts/Bills/Gazette/SI PDFs from gov.bw, Parliament Speaks, "
            "BURS, and statutory agency hosts. Skipped botswanalaws.com / SAFLII / "
            "laws.co.bw. elaws.gov.bw (AGC e-Laws) preferred by gov.bw but not "
            "reachable here. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
