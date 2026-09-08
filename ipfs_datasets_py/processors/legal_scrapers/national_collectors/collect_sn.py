#!/usr/bin/env python3
"""Senegal: Journal Officiel — jo.gouv.sn (primary, live+Wayback) + archives.sn official JO PDFs."""
from __future__ import annotations
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "sn", "Senegal", "fr"
SOURCE_TYPE = "jo_senegal"
LICENSE = (
    "Journal Officiel de la République du Sénégal "
    "(jo.gouv.sn / archives.sn Archives publiques). "
    "Authentic JO text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=http://www.jo.gouv.sn/)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.)\s+\d+[a-zA-Z]?)\b")
ARCHIVES_API = "https://www.archives.sn/api/documents"
ARCHIVES_FICHIER = "https://www.archives.sn/api/fichiers/{fid}"
log = logging.getLogger("sn")


def _add(items, seen, ident, url, meta=None):
    if not url or url in seen:
        return
    seen.add(url)
    items.append((ident, url, meta or {}))


def discover_jo_live(items, seen):
    """Primary: scrape jo.gouv.sn HTML for PDF / article / spip links."""
    for seed in ("http://www.jo.gouv.sn/", "https://www.jo.gouv.sn/", "http://jo.gouv.sn/"):
        try:
            # Short timeout: live host is often unreachable.
            r = live_get(seed, ua=UA, verify=False, timeout=(8, 20), retries=1)
        except Exception as exc:
            log.info("seed fail %s: %s", seed, exc)
            continue
        for href in re.findall(r'href="([^"]+)"', r.text or ""):
            url = urljoin(seed, href)
            if ".pdf" in url.lower() or "article" in url.lower() or "spip.php" in url:
                ident = Path(url.split("?")[0]).stem[:120] or re.sub(r"\W+", "-", url)[-80:]
                _add(items, seen, ident, url, {"portal": "jo.gouv.sn"})


def discover_jo_cdx(items, seen):
    """Wayback CDX of official jo.gouv.sn URLs only."""
    for prefix in ("jo.gouv.sn/", "www.jo.gouv.sn/"):
        try:
            hits = cdx_urls(prefix, limit=env_int("CDX_LIMIT", 150), match_type="prefix")
        except Exception as exc:
            log.info("cdx fail %s: %s", prefix, exc)
            continue
        for h in hits:
            orig = h.get("original") or ""
            if not orig:
                continue
            if ".pdf" in orig.lower() or "article" in orig.lower():
                ident = Path(orig.split("?")[0]).stem[:120] or re.sub(r"\W+", "-", orig)[-80:]
                _add(items, seen, ident, orig, {"portal": "jo.gouv.sn_wayback"})


def discover_archives(items, seen, *, max_pages: int = 8, page_limit: int = 50):
    """Official Archives publiques du Sénégal JO PDFs (archives.sn). Secondary seed."""
    for page in range(1, max_pages + 1):
        url = f"{ARCHIVES_API}?type=official_journal&limit={page_limit}&page={page}"
        try:
            r = live_get(url, ua=UA, verify=True, timeout=(15, 40), retries=2)
        except Exception as exc:
            log.info("archives api fail page=%s: %s", page, exc)
            break
        if getattr(r, "status_code", 0) != 200:
            log.info("archives api http_%s page=%s", r.status_code, page)
            break
        try:
            data = r.json()
        except Exception:
            try:
                data = json.loads(r.text or "")
            except Exception as exc:
                log.info("archives api json fail: %s", exc)
                break
        docs = data.get("documents") or []
        if not docs:
            break
        for doc in docs:
            if (doc.get("type") or "") != "official_journal":
                continue
            f = doc.get("file") or {}
            fid = f.get("id")
            if not fid:
                continue
            try:
                fsize = int(f.get("filesize") or 0)
            except Exception:
                fsize = 0
            # Skip oversized PDFs (world_lib MAX_PDF ~35MB); leave headroom.
            if fsize and fsize > 32 * 1024 * 1024:
                continue
            slug = (doc.get("slug") or f"jo-{doc.get('id')}")[:120]
            pdf_url = ARCHIVES_FICHIER.format(fid=fid)
            _add(
                items,
                seen,
                slug,
                pdf_url,
                {
                    "portal": "archives.sn",
                    "title": doc.get("title"),
                    "publish_date": doc.get("publish_date"),
                    "filename": f.get("filename_download"),
                    "page_url": f"https://www.archives.sn/docs/journal-officiel/{slug}",
                },
            )
        total_pages = (data.get("pagination") or {}).get("totalPages") or page
        if page >= int(total_pages):
            break


def discover():
    items, seen = [], set()
    discover_jo_live(items, seen)
    live_n = len(items)
    arch_pages = env_int("ARCHIVES_PAGES", 6)
    # Keep jo.gouv.sn primary when live discovery works; if live is near-zero
    # (common), seed archives.sn next so the pilot is not starved by slow CDX.
    if live_n < 5:
        discover_archives(items, seen, max_pages=arch_pages, page_limit=50)
        discover_jo_cdx(items, seen)
    else:
        discover_jo_cdx(items, seen)
        discover_archives(items, seen, max_pages=arch_pages, page_limit=50)
    log.info("catalog total=%s (jo_live=%s)", len(items), live_n)
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 40)
    max_seconds = env_int("MAX_SECONDS", 2000)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    portals = {}
    for ident, url, meta in discover():
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=150)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error"), "portal": meta.get("portal")})
            continue
        title = (meta.get("title") or "").strip() or next(
            (ln.strip()[:240] for ln in text.splitlines() if len(ln.strip()) > 18),
            ident,
        )
        portal = meta.get("portal") or "unknown"
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title,
            text=text,
            source_url=meta.get("page_url") or url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_sn.py",
            date=meta.get("publish_date"),
            article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "portal": portal, "fichier_url": url if portal == "archives.sn" else None},
        ):
            ok += 1
            done.add(rid)
            portals[portal] = portals.get(portal, 0) + 1
            log.info("ok %s portal=%s chars=%s", ident[:60], portal, len(text))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Journal Officiel du Sénégal",
        source_urls=[
            "http://www.jo.gouv.sn/",
            "https://www.archives.sn/docs/journal-officiel",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="JO issues incomplete; jo.gouv.sn often unreachable — archives.sn official PDFs used as secondary",
        notes=f"Official JO Senegal. portals={portals}. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s portals=%s", ok, skip, fail, portals)


if __name__ == "__main__":
    main()
