#!/usr/bin/env python3
"""Yemen: MoJ LawsMD PDFs + yemen-nic.info official laws DB.

Official sources only:
  https://moj.gov.ye/LawsMD/{n}     (primary PDF modules; LawsMD/4 was live PDF)
  https://yemen-nic.info/db/laws_ye/ (secondary official NIC legislation DB)

Discover law PDF/HTML on those official hosts only. Exclude commercial mirrors.
Live first; Wayback of official URLs on fail. No WAF bypass.
"""
from __future__ import annotations

import html as htmlmod
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "ye", "Yemen", "ar"
SOURCE_TYPE = "moj_ye"
LICENSE = (
    "Official Yemeni legislation texts from the Ministry of Justice (moj.gov.ye) "
    "and the National Information Center (yemen-nic.info). Authentic official text "
    "prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://moj.gov.ye/)"
NIC = "http://www.yemen-nic.info"
MOJ = "http://moj.gov.ye"
SECTIONS = [541, 542, 543]
DETAIL_RE = re.compile(r"(?:detail|dostor)\.php\?ID=(\d+)", re.I)
TITLE_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
LAWSMD_ROW = re.compile(
    r"(?is)<tr[^>]*>\s*<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>(.*?)</td>.*?"
    r'href=["\']/LawsMD/(\d+)["\']',
)
ART = re.compile(r"(?im)^\s*((?:المادة|مادة)\s*\(?\s*[0-9\u0660-\u0669]+\s*\)?)")
log = logging.getLogger("ye")


def _clean(s: str) -> str:
    s = htmlmod.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def discover_lawsmd() -> list[tuple[str, str, str, dict]]:
    items: list[tuple[str, str, str, dict]] = []
    seen: set[str] = set()
    # List pages
    # LawsM listing redirects HTTP->HTTPS which SSLEOFs from this host; range+CDX only.
    pages = []
    if env_int("YE_LAWSM_PAGES", 0) > 0:
        pages = [f"{MOJ}/LawsM"]
        for p in range(1, env_int("YE_LAWSM_PAGES", 0) + 1):
            pages.append(f"{MOJ}/LawsM?page={p}")
            pages.append(f"{MOJ}/Home/LawsM?page={p}")
    for seed in pages:
        try:
            r = live_get(seed, ua=UA, verify=False, timeout=(15, 45), retries=2)
        except Exception as exc:
            log.info("LawsM fail %s: %s", seed, exc)
            continue
        html = r.text or ""
        for m in LAWSMD_ROW.finditer(html):
            n, title, n2 = m.group(1), _clean(m.group(2)), m.group(3)
            num = n2 or n
            ident = f"lawsmd-{num}"
            if ident in seen:
                continue
            seen.add(ident)
            items.append((ident, f"{MOJ}/LawsMD/{num}", title or f"LawsMD/{num}", {"portal": "moj_lawsm"}))
        for m in re.finditer(r"/LawsMD/(\d+)", html):
            num = m.group(1)
            ident = f"lawsmd-{num}"
            if ident in seen:
                continue
            seen.add(ident)
            items.append((ident, f"{MOJ}/LawsMD/{num}", f"LawsMD/{num}", {"portal": "moj_lawsm"}))
        time.sleep(0.4)
    # Range seed for modules not listed on first pages
    max_n = env_int("YE_LAWSMD_MAX", 80)
    for n in range(1, max_n + 1):
        ident = f"lawsmd-{n}"
        if ident in seen:
            continue
        seen.add(ident)
        items.append((ident, f"{MOJ}/LawsMD/{n}", f"LawsMD/{n}", {"portal": "moj_lawsmd_range"}))
    # CDX
    if not env_int("SKIP_CDX", 0):
        for hit in cdx_urls("moj.gov.ye/LawsMD/", limit=env_int("YE_CDX_LIMIT", 120), match_type="prefix"):
            orig = (hit.get("original") or "").strip()
            m = re.search(r"/LawsMD/(\d+)", orig)
            if not m:
                continue
            num = m.group(1)
            ident = f"lawsmd-{num}"
            if ident in seen:
                continue
            seen.add(ident)
            items.append((ident, f"{MOJ}/LawsMD/{num}", f"LawsMD/{num}", {"portal": "moj_cdx", "cdx_ts": hit.get("timestamp")}))
    log.info("lawsmd catalog=%s", len([i for i in items if i[0].startswith("lawsmd")]))
    return items


def discover_nic() -> list[tuple[str, str, str, dict]]:
    items: list[tuple[str, str, str, dict]] = []
    seen: set[str] = set()
    # Constitution
    items.append(("nic-dostor-5846", f"{NIC}/db/laws_ye/dostor.php?ID=5846", "دستور الجمهورية اليمنية", {"portal": "nic_dostor"}))
    seen.add("5846")
    seeds = [f"{NIC}/db/laws_ye/"] + [f"{NIC}/db/laws_ye/section.php?SECTION_ID={s}" for s in SECTIONS]
    queue = list(seeds)
    visited = set()
    max_pages = env_int("YE_NIC_PAGES", 25)
    while queue and len(visited) < max_pages:
        seed = queue.pop(0)
        if seed in visited:
            continue
        visited.add(seed)
        try:
            r = live_get(seed, ua=UA, verify=True, timeout=(15, 45), retries=2)
        except Exception as exc:
            log.info("nic seed fail %s: %s", seed, exc)
            continue
        html = r.text or ""
        for m in DETAIL_RE.finditer(html):
            did = m.group(1)
            if did in seen:
                continue
            seen.add(did)
            kind = "dostor" if "dostor.php" in m.group(0).lower() else "detail"
            url = f"{NIC}/db/laws_ye/{kind}.php?ID={did}"
            items.append((f"nic-{did}", url, f"NIC law {did}", {"portal": "nic"}))
        for href in re.findall(r'href=["\']([^"\']*PAGEN_1=\d+[^"\']*)["\']', html, re.I):
            full = urljoin(seed, href.replace("&amp;", "&"))
            if "yemen-nic.info" in full and full not in visited:
                queue.append(full)
        time.sleep(0.35)
    if not env_int("SKIP_CDX", 0):
        for prefix in (
            "yemen-nic.info/db/laws_ye/detail.php",
            "www.yemen-nic.info/db/laws_ye/detail.php",
        ):
            for hit in cdx_urls(prefix, limit=env_int("YE_CDX_LIMIT", 150), match_type="prefix"):
                orig = (hit.get("original") or "").replace("&amp;", "&")
                m = DETAIL_RE.search(orig)
                if not m:
                    continue
                did = m.group(1)
                if did in seen:
                    continue
                seen.add(did)
                items.append(
                    (f"nic-{did}", f"{NIC}/db/laws_ye/detail.php?ID={did}", f"NIC law {did}",
                     {"portal": "nic_cdx", "cdx_ts": hit.get("timestamp")})
                )
    log.info("nic catalog=%s", len([i for i in items if i[0].startswith("nic")]))
    return items


def discover():
    # Prefer MoJ PDFs first, then NIC HTML
    lawsmd = discover_lawsmd()
    nic = discover_nic()
    return lawsmd + nic


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 60)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    catalog = discover()
    ok = skip = fail = 0
    methods: dict[str, int] = {}
    portals: dict[str, int] = {}
    for ident, url, title, meta in catalog:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        portal = (meta or {}).get("portal") or "unknown"
        verify = "moj.gov.ye" not in url  # MoJ TLS often EOFs on LawsMD
        # actually always try verify=False for moj, True for nic but fetch_official falls back
        verify = False if "moj.gov.ye" in url else True
        got = fetch_official(
            url, ua=UA, verify=verify, min_text=80, wayback=True, wayback_ts=(meta or {}).get("cdx_ts")
        )
        # retry moj with verify=False already; if fail try http
        if got.get("status") != "success" and url.startswith("https://moj.gov.ye/"):
            alt = "http://" + url[len("https://") :]
            got2 = fetch_official(alt, ua=UA, verify=False, min_text=80, wayback=True)
            if got2.get("status") == "success":
                got = got2
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error"), "portal": portal})
            time.sleep(0.4)
            continue
        if "detail.php" in url or "dostor.php" in url:
            raw = got.get("content") or b""
            if isinstance(raw, bytes):
                raw_s = raw.decode("utf-8", "replace")
                tm = TITLE_RE.search(raw_s)
                if tm:
                    title = _clean(tm.group(1))[:240] or title
        method = got.get("method") or ""
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title or ident,
            text=text,
            source_url=url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_ye.py",
            article_re=ART,
            extra_meta={"fetch_method": method, "portal": portal, "retrieval": "archive" if "wayback" in method else "live"},
        ):
            ok += 1
            done.add(rid)
            methods[method] = methods.get(method, 0) + 1
            portals[portal] = portals.get(portal, 0) + 1
            log.info("ok %s chars=%s method=%s portal=%s", ident, len(text), method, portal)
        else:
            fail += 1
        time.sleep(0.45)
    write_summary(
        CC,
        country=COUNTRY,
        source="Yemen MoJ LawsMD + NIC laws DB",
        source_urls=[f"{MOJ}/LawsM", f"{MOJ}/LawsMD/", f"{NIC}/db/laws_ye/"],
        license_text=LICENSE,
        discovered=len(catalog),
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="MoJ LawsMD PDFs + yemen-nic.info legislation HTML; incomplete vs full gazette corpus",
        notes=f"Official moj.gov.ye + yemen-nic.info only. portals={portals} methods={methods}. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s portals=%s methods=%s", ok, skip, fail, portals, methods)


if __name__ == "__main__":
    main()
