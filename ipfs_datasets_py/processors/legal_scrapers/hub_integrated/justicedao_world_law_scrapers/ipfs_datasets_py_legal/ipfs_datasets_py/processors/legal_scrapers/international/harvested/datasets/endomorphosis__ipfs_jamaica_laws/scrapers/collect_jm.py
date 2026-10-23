#!/usr/bin/env python3
"""Jamaica: Laws of Jamaica (laws.moj.gov.jm) + MOJ / Parliament official PDFs.

Official-only densify collector:
  - Revised Statutes + Constitution downloads from laws.moj.gov.jm
  - Revised Subsidiary Legislation compilations
  - Gazettes (Act / Order / Regulations titled) via library gazettes API
  - Live MOJ / Parliament PDF seeds + Wayback/CDX of official PDF prefixes

Not vLex / commercial aggregators. Authentic official text prevails. Not legal advice.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote, quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary, ensure_dirs
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "jm", "Jamaica", "en"
SOURCE_TYPE = "laws_moj_jamaica"
LICENSE = (
    "Laws of Jamaica — Ministry of Justice / Parliament "
    "(laws.moj.gov.jm, moj.gov.jm, japarliament.gov.jm). "
    "Authentic official text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://laws.moj.gov.jm/)"
)
# Commonwealth / JM Cap drafting: Section / PART / Schedule / numbered Cap sections
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|PART|Part|SCHEDULE|Schedule)\s+"
    r"[0-9IVXLC]+[A-Za-z]?\.?|"
    r"s\.\s*[0-9]+[A-Za-z]?|"
    r"[0-9]{1,3}[A-Za-z]?\.(?=\s+(?:\([0-9]+\)|[A-Z\"'“‘]|Short title|Interpretation|This )))"
)
log = logging.getLogger("jm")

LAWS = "https://laws.moj.gov.jm"
HOST_OK = (
    "laws.moj.gov.jm",
    "moj.gov.jm",
    "www.moj.gov.jm",
    "japarliament.gov.jm",
    "www.japarliament.gov.jm",
    "lipj.gov.jm",  # Legal Information Portal Jamaica (official LRC-adjacent)
)
SKIP_RE = re.compile(
    r"(favicon|newsletter|brochure|powerpoint|pptx|order.?of.?the.?day|"
    r"hansard|minutes|agenda|curriculum|vacancy|job.?ad|"
    r"application.?form|flyer|poster)",
    re.I,
)
CDX_PREFIXES = (
    "moj.gov.jm/sites/default/files/laws/",
    "www.moj.gov.jm/sites/default/files/laws/",
    "moj.gov.jm/sites/default/files/docs/",
    "www.moj.gov.jm/sites/default/files/docs/",
    "japarliament.gov.jm/attachments/",
    "www.japarliament.gov.jm/attachments/",
    "laws.moj.gov.jm/legislation/",
)
SEED_PAGES = (
    "https://moj.gov.jm/laws",
    "https://moj.gov.jm/",
    "https://japarliament.gov.jm/",
    "https://laws.moj.gov.jm/library",
    "https://laws.moj.gov.jm/library/statutes/revised",
)
CONSTITUTION_SLUG = "the-jamaica-constitution-order-in-council-1962"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/json,application/pdf,*/*",
            "Accept-Language": "en-GB,en;q=0.9",
        }
    )
    s.verify = False
    return s


def _host_ok(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(h == host or host.endswith("." + h) for h in HOST_OK)


def _norm(url: str) -> str:
    url = (url or "").split("#")[0].strip()
    if not url:
        return ""
    url = url.replace("http://", "https://").replace(":80/", "/")
    return url


def _add(items: list, seen: set, ident: str, url: str, title: str | None = None, kind: str = ""):
    url = _norm(url)
    if not url or not _host_ok(url):
        return
    if SKIP_RE.search(url):
        return
    if url in seen:
        return
    seen.add(url)
    ident = (ident or Path(urlparse(url).path).stem or "doc")[:160]
    items.append((ident, url, title or "", kind))


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _pdf_url(path: str) -> str:
    """Build absolute laws.moj.gov.jm PDF URL with encoded filename."""
    path = path.strip()
    if path.startswith("http"):
        return _norm(path)
    bits = [quote(unquote(b), safe="") for b in path.strip("/").split("/")]
    return LAWS + "/" + "/".join(bits)



def discover_statutes(sess: requests.Session, items: list, seen: set) -> int:
    """All revised statutes via laws.moj.gov.jm DataTables GET API."""
    n0 = len(items)
    start = 0
    page = env_int("STATUTE_PAGE", 100)
    total = None
    while True:
        try:
            rr = sess.get(
                f"{LAWS}/library/statutes/revised",
                params={
                    "_dt": "dt",
                    "draw": 1,
                    "start": start,
                    "length": page,
                    "search[value]": "",
                },
                timeout=60,
                headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
            )
            d = rr.json()
        except Exception as exc:
            log.info("statutes dt err start=%s: %s", start, exc)
            break
        if total is None:
            total = int(d.get("recordsTotal") or 0)
            log.info("statutes catalog total=%s", total)
        rows = d.get("data") or []
        if not rows:
            break
        for row in rows:
            title_html = row.get("shortTitle") or ""
            hrefs = re.findall(r'href="(/library/statute/[^"]+)"', title_html)
            title = _strip_html(title_html)
            slug = None
            for h in hrefs:
                if h.endswith("/download"):
                    continue
                slug = h.rstrip("/").split("/")[-1]
                break
            if not slug:
                actions = row.get("actions") or ""
                m = re.search(r"/library/statute/([^/\"]+)/download", actions)
                if m:
                    slug = m.group(1)
            if not slug:
                continue
            url = f"{LAWS}/library/statute/{slug}/download"
            _add(items, seen, f"statute-{slug}", url, title or slug, "STATUTE")
        start += len(rows)
        if total is not None and start >= total:
            break
        if start >= env_int("STATUTE_MAX", 5000):
            break
    # Constitution explicit (also in catalog, but ensure first-class)
    _add(
        items,
        seen,
        f"statute-{CONSTITUTION_SLUG}",
        f"{LAWS}/library/statute/{CONSTITUTION_SLUG}/download",
        "The Jamaica (Constitution) Order in Council 1962",
        "CONSTITUTION",
    )
    return len(items) - n0


def discover_subsidiary(sess: requests.Session, items: list, seen: set) -> int:
    """Subsidiary legislation compilation PDFs linked from parent Act pages."""
    n0 = len(items)
    try:
        rr = sess.get(f"{LAWS}/library/subsidiary-legislation/revised", timeout=60)
    except Exception as exc:
        log.info("subsidiary index err: %s", exc)
        return 0
    links = sorted(
        set(
            re.findall(
                r'href="(/library/subsidiary-legislation/(?!revised)[^"?#]+)"',
                rr.text or "",
            )
        )
    )
    max_sub = env_int("SUBSID_MAX", 400)
    for path in links[:max_sub]:
        slug = path.rstrip("/").split("/")[-1]
        detail_url = urljoin(LAWS, path)
        try:
            dr = sess.get(detail_url, timeout=45)
        except Exception as exc:
            log.info("subsid detail fail %s: %s", slug, exc)
            continue
        pdfs = re.findall(r'value="(/legislation/[^"]+\.pdf)"', dr.text or "", re.I)
        if not pdfs:
            pdfs = re.findall(r'href="(/legislation/[^"]+\.pdf)"', dr.text or "", re.I)
        title_m = re.search(r"<title>([^|<]+)", dr.text or "")
        title = (title_m.group(1).strip() if title_m else slug) + " (subsidiary)"
        for p in pdfs:
            url = _pdf_url(p)
            _add(items, seen, f"subsid-{slug}", url, title, "SUBSID")
            break  # one compilation PDF per parent
    return len(items) - n0


def discover_gazettes(sess: requests.Session, items: list, seen: set) -> int:
    """Official gazettes with Act/Order/Regulations titles (recent years)."""
    n0 = len(items)
    years = list(range(env_int("GAZ_YEAR_FROM", 2018), env_int("GAZ_YEAR_TO", 2025)))
    max_gaz = env_int("GAZ_MAX", 120)
    keep = re.compile(r"\b(Act|Order|Regulations?|Rules?|Proclamation)\b", re.I)
    for year in reversed(years):
        if len(items) - n0 >= max_gaz:
            break
        start = 0
        page = 50
        while len(items) - n0 < max_gaz:
            try:
                rr = sess.post(
                    f"{LAWS}/library/gazettes/{year}",
                    data={
                        "draw": 1,
                        "start": start,
                        "length": page,
                        "search[value]": "",
                    },
                    timeout=60,
                    headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
                )
                d = rr.json()
            except Exception as exc:
                log.info("gazette %s err: %s", year, exc)
                break
            rows = d.get("data") or []
            if not rows:
                break
            filtered = int(d.get("recordsFiltered") or 0)
            for row in rows:
                if len(items) - n0 >= max_gaz:
                    break
                title = _strip_html(str(row[0] if isinstance(row, list) else row.get("title") or ""))
                ref_html = str(row[1] if isinstance(row, list) else "")
                if title and not keep.search(title):
                    continue
                hrefs = re.findall(r'href="(/library/gazette/[^"]+)"', ref_html)
                if not hrefs:
                    continue
                slug = hrefs[0].rstrip("/").split("/")[-1]
                detail = urljoin(LAWS, hrefs[0])
                try:
                    dr = sess.get(detail, timeout=45)
                except Exception:
                    continue
                pdfs = re.findall(r'value="(/legislation/[^"]+\.pdf)"', dr.text or "", re.I)
                for p in pdfs:
                    url = _pdf_url(p)
                    _add(items, seen, f"gazette-{slug}", url, title or slug, "GAZETTE")
                    break
            start += len(rows)
            if start >= filtered:
                break
    return len(items) - n0


def discover_seeds_and_cdx(items: list, seen: set) -> int:
    n0 = len(items)
    sess = _session()
    for su in SEED_PAGES:
        try:
            r = sess.get(su, timeout=50)
        except Exception as exc:
            log.info("seed fail %s: %s", su, exc)
            continue
        for href in re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', r.text or "", re.I):
            url = urljoin(su, href)
            stem = Path(urlparse(url).path).stem[:140]
            _add(items, seen, stem, url, stem, "SEED")
    cdx_limit = env_int("CDX_LIMIT", 1500)
    per = max(200, cdx_limit // max(len(CDX_PREFIXES), 1))
    for prefix in CDX_PREFIXES:
        for h in cdx_urls(
            prefix,
            limit=per,
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = _norm((h.get("original") or ""))
            if not orig or ".pdf" not in orig.lower():
                continue
            stem = Path(urlparse(orig).path).stem[:140]
            _add(items, seen, stem, orig, stem, "CDX")
    return len(items) - n0


def discover() -> list[tuple[str, str, str, str]]:
    items: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    sess = _session()
    n_st = discover_statutes(sess, items, seen)
    log.info("discovered statutes+=%s", n_st)
    # Prefer statutes/constitution before subsidiary/gazettes/CDX
    n_sub = discover_subsidiary(sess, items, seen) if env_int("INCLUDE_SUBSID", 1) else 0
    log.info("discovered subsid+=%s", n_sub)
    n_gaz = discover_gazettes(sess, items, seen) if env_int("INCLUDE_GAZ", 1) else 0
    log.info("discovered gazettes+=%s", n_gaz)
    n_cdx = discover_seeds_and_cdx(items, seen)
    log.info("discovered seeds+cdx+=%s catalog=%s", n_cdx, len(items))
    # Stable priority: CONSTITUTION / STATUTE first
    def prio(it):
        kind = it[3]
        order = {"CONSTITUTION": 0, "STATUTE": 1, "SUBSID": 2, "GAZETTE": 3, "SEED": 4, "CDX": 5}.get(kind, 9)
        return (order, it[0])

    items.sort(key=prio)
    return items


def main():
    ensure_dirs(CC)
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 180)
    max_seconds = env_int("MAX_SECONDS", 5400)
    t_start = time.time()
    done = existing_ids(CC)
    # Also skip by known hub source URL stems to reduce near-dupes from old moj paths
    known_urls = set()
    for p in (Path(os.environ.get("LEGAL_CORPORA_ROOT", "{_CORPORA}")) / CC / "instruments").glob("*.json"):
        try:
            import json as _json

            rec = _json.loads(p.read_text(encoding="utf-8"))
            u = (rec.get("source_url") or "").split("?")[0]
            if u:
                known_urls.add(u)
                known_urls.add(u.replace("https://www.", "https://").replace("https://moj.", "https://www.moj."))
        except Exception:
            pass
    ok = skip = fail = 0
    catalog = discover()
    log.info("catalog size=%s existing=%s", len(catalog), len(done))
    for ident, url, title_hint, kind in catalog:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            log.info("time budget exhausted")
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        if url in known_urls:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=150)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "kind": kind, "reason": got.get("error")})
            continue
        title = title_hint or next((ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 18), ident)
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE if kind in {"STATUTE", "CONSTITUTION", "SUBSID", "GAZETTE"} else "moj_jamaica",
            license_text=LICENSE,
            collector="collect_jm.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "jm_kind": kind},
        ):
            ok += 1
            done.add(rid)
            known_urls.add(url)
            log.info("ok kind=%s %s chars=%s", kind, ident[:70], len(text))
        else:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "kind": kind, "reason": "save_failed"})
    write_summary(
        CC,
        country=COUNTRY,
        source="Laws of Jamaica / MOJ / Parliament",
        source_urls=[
            "https://laws.moj.gov.jm/",
            "https://moj.gov.jm/",
            "https://japarliament.gov.jm/",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete (laws.moj.gov.jm statutes+subsid+gazettes densify)",
        notes=(
            "Official Jamaican government law PDFs from laws.moj.gov.jm / moj.gov.jm / "
            "japarliament.gov.jm only. Cap/Section article splits. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
