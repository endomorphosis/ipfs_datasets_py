#!/usr/bin/env python3
"""Seychelles (sc): official Acts / Bills / SI / Gazette / Constitution PDFs.

Official only:
  - https://www.gazette.sc/          (Official Gazette)
  - https://src.gov.sc/              (Seychelles Revenue Commission legislation)
  - https://www.finance.gov.sc/      (Ministry of Finance Acts / SI)
  - https://www.health.gov.sc/       (Ministry of Health Acts)
  - https://www.statehouse.gov.sc/   (State House)
  - https://www.gov.sc/              when reachable
  - https://nationalassembly.gov.sc/ when reachable
  - https://www.judiciary.sc/        (Judiciary — Constitution / codes)
  - https://ecs.sc/                  (Electoral Commission — Elections Act / SI)
  - Wayback/CDX of the same official *.gov.sc / *.sc URLs

NOT SeyLII (seylii.org), AfricanLII, gazettes.africa, commercial DBs.
No WAF bypass. Live-first; Wayback of same official URL on fail.
Skip PDFs >12MB. Leave km/mg/mu alone. Not legal advice.
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import (
    cdx_urls,
    env_int,
    fetch_official,
    live_get,
    save_instrument,
    setup_log,
    slug_id,
)

CC, COUNTRY, LANG = "sc", "Seychelles", "en"
SOURCE_TYPE = "seychelles_official_gazette_acts"
LICENSE = (
    "Republic of Seychelles — Official Gazette (gazette.sc) / SRC (src.gov.sc) / "
    "Ministry of Finance (finance.gov.sc) / Health (health.gov.sc) / State House "
    "(statehouse.gov.sc) / Judiciary (judiciary.sc) / Electoral Commission (ecs.sc) / "
    "gov.sc / National Assembly when published. Authentic Official Gazette / Act text "
    "prevails. Not SeyLII / AfricanLII. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.gazette.sc/)"
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|Cap\.?|Chapter|Part|Regulation|Reg\.)\s*[0-9]+[A-Za-z]?)\b"
)
log = logging.getLogger("sc")
MAX_PDF_BYTES = 12 * 1024 * 1024

ALLOWED_SUFFIXES = (
    "gov.sc",
    "gazette.sc",
    "judiciary.sc",
    "ecs.sc",
    "statehouse.gov.sc",
    "nationalassembly.gov.sc",
    "nationalassembly.sc",
)
ALLOWED_EXACT = (
    "gov.sc",
    "gazette.sc",
    "judiciary.sc",
    "ecs.sc",
    "egov.sc",
)

BLOCK_HOST = re.compile(
    r"(seylii\.org|africanlii|saflii|commonlii|gazettes\.africa|"
    r"law\.africa|ulii\.org|worldlii|bailii)",
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
    r"legislation|/uploads/|/sites/default/files/"
    r")",
    re.I,
)
DROP_RE = re.compile(
    r"(seylii|africanlii|saflii|gazettes\.africa|law\.africa|"
    r"press[_\-\s]?release|newsletter|vacancy|tender|brochure|"
    r"strategic[_\-\s]?plan|annual[_\-\s]?report|statistical[_\-\s]?report|"
    r"calendar|poster|leaflet|breast|cancer|useful[_\-\s]?information|"
    r"vital[_\-\s]?statistics|primary[_\-\s]?healthcare|"
    r"hospital[_\-\s]?services|workshop|speech|manifesto|"
    r"party[_\-\s]?constitution|one[_\-\s]?seychelles|laliberte|"
    r"snap[_\-\s]?constitution|spnm|lns[_\-\s]?constitution|"
    r"us[_\-\s]?constitution[_\-\s]?2023|mls[_\-\s]?constitution|"
    r"lds[_\-\s]?constitution|sum[_\-\s]?constitution|"
    r"public[_\-\s]?consultative|facebook|twitter|youtube|"
    r"banner|logo|photo|recruitment|application[_\-\s]?form|"
    r"comoros|mauritius|madagascar)",
    re.I,
)
TEXT_KEEP_RE = re.compile(
    r"("
    r"REPUBLIC OF SEYCHELLES|SEYCHELLES|"
    r"AN ACT\b|A BILL\b|BE IT ENACTED|"
    r"Short title|This Act may be cited|"
    r"OFFICIAL GAZETTE|GOVERNMENT GAZETTE|"
    r"Statutory Instrument|S\.I\.\s*\d|"
    r"CONSTITUTION OF THE REPUBLIC|"
    r"ARRANGEMENT OF SECTIONS|"
    r"National Assembly|President of the Republic|"
    r"Date of Assent|I assent|"
    r"PENAL CODE|CIVIL CODE|CRIMINAL PROCEDURE"
    r")",
    re.I,
)

LIVE_PAGES = (
    "https://www.gazette.sc/",
    "https://src.gov.sc/legislation/",
    "https://src.gov.sc/enabling-laws/",
    "https://www.finance.gov.sc/resources/legislations/",
    "https://www.finance.gov.sc/",
    "https://www.health.gov.sc/policy-legislation/",
    "https://www.statehouse.gov.sc/downloads",
    "https://www.statehouse.gov.sc/",
    "https://www.judiciary.sc/seychelles-law/",
    "https://www.judiciary.sc/",
    "https://ecs.sc/elections-act/",
    "https://ecs.sc/political-parties-act/",
    "https://ecs.sc/regulations/",
    "https://ecs.sc/legislative-amendments/",
    "https://www.gov.sc/",
    "https://nationalassembly.gov.sc/",
    "https://www.nationalassembly.gov.sc/",
)

WP_BASES = (
    "https://www.finance.gov.sc",
    "https://src.gov.sc",
    "https://www.health.gov.sc",
    "https://www.judiciary.sc",
    "https://ecs.sc",
)

CDX_PREFIXES = (
    "www.gazette.sc/sites/default/files/",
    "gazette.sc/sites/default/files/",
    "www.gazette.sc/",
    "src.gov.sc/wp-content/uploads/",
    "www.src.gov.sc/wp-content/uploads/",
    "www.finance.gov.sc/wp-content/uploads/",
    "finance.gov.sc/wp-content/uploads/",
    "www.health.gov.sc/wp-content/uploads/",
    "www.judiciary.sc/wp-content/uploads/",
    "judiciary.sc/wp-content/uploads/",
    "ecs.sc/wp-content/uploads/",
    "www.statehouse.gov.sc/uploads/",
    "www.gov.sc/",
    "nationalassembly.gov.sc/",
    "www.nationalassembly.gov.sc/",
)


def _host_ok(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    if not host or BLOCK_HOST.search(host):
        return False
    if host in ALLOWED_EXACT:
        return True
    if host.endswith(".gov.sc") or host == "gov.sc":
        return True
    return any(host == s or host.endswith("." + s) for s in ALLOWED_SUFFIXES)


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _ident_from_url(url: str) -> str:
    host = (urlsplit(url).hostname or "sc").lower().replace("www.", "")
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
    if re.search(r"regulation|statutory|\bsi[_\-\s]?\d|s\.i", low):
        return 18
    if re.search(r"gazette", low):
        return 22
    return 30


def _should_keep(url: str, title: str = "") -> bool:
    blob = unquote(url) + " " + (title or "")
    if not _host_ok(url):
        return False
    if DROP_RE.search(blob):
        # still allow clear Act/SI/Constitution filenames
        if not re.search(
            r"(?i)(/act[-_ ]|\bact[-_ ]|amendment.?act|constitution.of.the.republic|"
            r"penal.?code|civil.?code|/si[-_ ]|\bsi[-_ ]?\d|statutory|"
            r"official.?gazette|bill.?no)",
            blob,
        ):
            return False
        if re.search(
            r"(?i)(party.?constitution|one.?seychelles|laliberte|press.?release|"
            r"statistical.?report|strategic.?plan|annual.?report|poster|leaflet)",
            blob,
        ):
            return False
    # gazette.sc / judiciary codes always interesting if pdf
    host = (urlsplit(url).hostname or "").lower()
    if "gazette.sc" in host and re.search(r"(?i)(act|bill|si|s\.i|gazette|extraordinary)", blob):
        return True
    if "judiciary.sc" in host and re.search(
        r"(?i)(constitution|code|act|rules|procedure)", blob
    ):
        return True
    return bool(KEEP_RE.search(blob))


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
                r = live_get(api, ua=UA, timeout=(15, 45), retries=2)
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

    # Drupal-ish gazette listing pages (paginate lightly)
    for gpage in (
        "https://www.gazette.sc/",
        "https://www.gazette.sc/acts",
        "https://www.gazette.sc/bills",
        "https://www.gazette.sc/statutory-instruments",
        "https://www.gazette.sc/gazettes",
    ):
        for href, title in _scrape_page_pdfs(gpage):
            add(href, title=title, priority=_priority(href + " " + title))
        time.sleep(0.1)

    if env_int("INCLUDE_CDX_PDF", 1):
        for prefix in CDX_PREFIXES:
            try:
                hits = cdx_urls(
                    prefix,
                    limit=env_int("CDX_LIMIT", 100),
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
    t_start = time.time()
    done = existing_ids(CC)
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
        if rid in done:
            skip += 1
            continue
        if size_hint and size_hint > MAX_PDF_BYTES:
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
        if not TEXT_KEEP_RE.search(text[:12000]):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "text_not_legal"})
            continue
        use_title = title or ident
        for line in text.splitlines():
            if len(line.strip()) > 18:
                use_title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=use_title,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_sc.py",
            article_re=ART,
            extra_meta={
                "fetch_method": got.get("method"),
                "wayback_ts": ts,
                "size_hint": size_hint,
                "priority": pri,
            },
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:60], got.get("method"), len(text))
        else:
            fail += 1

    write_summary(
        CC,
        country=COUNTRY,
        source=(
            "Seychelles Official Gazette (gazette.sc) / SRC / Finance / Health / "
            "State House / Judiciary / ECS"
        ),
        source_urls=[
            "https://www.gazette.sc/",
            "https://src.gov.sc/legislation/",
            "https://src.gov.sc/enabling-laws/",
            "https://www.finance.gov.sc/resources/legislations/",
            "https://www.health.gov.sc/policy-legislation/",
            "https://www.statehouse.gov.sc/",
            "https://www.judiciary.sc/seychelles-law/",
            "https://ecs.sc/elections-act/",
            "https://www.gov.sc/",
            "https://nationalassembly.gov.sc/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage=(
            "catalog-backed incomplete (gazette.sc + src.gov.sc + finance.gov.sc + "
            "health.gov.sc + judiciary.sc + ecs.sc live; nationalassembly/gov.sc "
            "often unreachable; PDFs >12MB skipped)"
        ),
        notes=(
            "Official *.gov.sc / gazette.sc / judiciary.sc / ecs.sc / statehouse only. "
            "Live-first; Wayback/CDX of same official URLs. NOT SeyLII (seylii.org) / "
            "AfricanLII. No WAF bypass. Not legal advice. sc=Seychelles (not km/mg/mu)."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s total_instruments=%s", ok, skip, fail, len(done))


if __name__ == "__main__":
    main()
