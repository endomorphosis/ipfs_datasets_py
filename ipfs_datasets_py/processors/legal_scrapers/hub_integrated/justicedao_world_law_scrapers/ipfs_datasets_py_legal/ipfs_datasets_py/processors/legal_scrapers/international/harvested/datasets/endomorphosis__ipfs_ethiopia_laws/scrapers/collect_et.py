#!/usr/bin/env python3
"""Ethiopia: Federal Negarit Gazette / MoJ proclamation & regulation PDFs.

Prefer justice.gov.et official PDF uploads over HTML shells.
Wayback of same official URLs OK. No LawEthiopia commercial archive.
No WAF bypass. Not legal advice.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, logging, re, shutil, sys, time
from pathlib import Path
from urllib.parse import urljoin, unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id, split_custom

CC, COUNTRY, LANG = "et", "Ethiopia", "am"
SOURCE_TYPE = "negarit_gazette"
LICENSE = (
    "Federal Negarit Gazette of the Federal Democratic Republic of Ethiopia as published "
    "via justice.gov.et. Authentic gazette text prevails. Not legal advice. "
    "Not LawEthiopia commercial archive."
)
UA = "legal-corpora-collector/1.0 (research; source=https://justice.gov.et/)"
ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|ARTICLE|አንቀጽ)\s*[0-9፩-፼]+[A-Za-z]?)\b"
)
log = logging.getLogger("et")
LIST_PAGES = [
    "https://www.justice.gov.et/en/laws/proclamations/",
    "https://justice.gov.et/en/laws/proclamations/",
    "https://www.justice.gov.et/am/laws/proclamations/",
    "https://justice.gov.et/am/laws/proclamations/",
    "https://justice.gov.et/en/laws/regulations/",
    "https://justice.gov.et/am/laws/regulations/",
]


def quarantine_junk() -> int:
    instr = ROOT / CC / "instruments"
    q = ROOT / CC / "quarantine_nonlaws"
    q.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in list(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        url = rec.get("source_url") or ""
        title = rec.get("title") or ""
        rid = rec.get("id") or p.stem
        drop = False
        if "Filter by Sector" in text[:1500]:
            drop = True
        if any(k in rid for k in ("-videos-", "-news-")):
            drop = True
        if "Interview" in title:
            drop = True
        # HTML law-page shells without proclamation body
        if "/law/" in url and ".pdf" not in url.lower():
            bodyish = ("NOW, THEREFORE" in text) or ("አንቀጽ" in text) or (text.count("Article") >= 3)
            if len(text) < 2500 and not bodyish:
                drop = True
        if drop:
            shutil.move(str(p), str(q / p.name))
            n += 1
            log.info("quarantine %s", p.name)
    return n


def add_url(items, seen, url, prefer=False):
    url = (url or "").split("#")[0]
    if not url.startswith("http"):
        return
    lowu = url.lower()
    if any(lowu.endswith(ext) or ext + "?" in lowu for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return
    if ".pdf.jpg" in lowu:
        return
    if url.rstrip("/").endswith(("/proclamations", "/laws", "/regulations", "/directives")):
        return
    key = url.lower()
    if key in seen:
        return
    seen.add(key)
    ident = re.sub(r"^https?://[^/]+/", "", url).replace("/", "-").replace("?", "-")
    ident = unquote(ident)[:160]
    items.append((ident, url, prefer))


def discover():
    items, seen = [], set()
    detail_pages = []

    for base in LIST_PAGES:
        for page in range(1, env_int("LIST_PAGES", 8) + 1):
            url = base if page == 1 else urljoin(base, f"page/{page}/")
            try:
                r = live_get(url, ua=UA, retries=1, verify=False)
            except Exception as exc:
                log.info("list %s %s", url, exc)
                break
            if r.status_code != 200:
                break
            html = r.text or ""
            for href in re.findall(r'href="([^"]+)"', html):
                full = urljoin(url, href)
                low = full.lower()
                if low.endswith(".pdf") or (".pdf" in low and not any(low.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"))):
                    if not any(ext in low for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
                        add_url(items, seen, full.split("?")[0], prefer=True)
                elif "jet_download" in low and "jet_download=" in low:
                    # skip bare homepage jet links that bounce to /en/ HTML
                    if len(full.split("jet_download=")[-1]) >= 20:
                        add_url(items, seen, full, prefer=False)  # PDF uploads first
                elif re.search(r"/(en|am)/law/", full):
                    detail_pages.append(full)
            # MoJ pagination often repeats the same sidebar PDFs; stop after a few pages
            if page >= 3 and ".pdf" not in html.lower() and "jet_download" not in html.lower() and "/law/" not in html.lower():
                break

    # Dedupe detail pages and follow for embedded PDFs
    dseen = set()
    details = []
    for d in detail_pages:
        k = d.lower().rstrip("/")
        if k not in dseen:
            dseen.add(k)
            details.append(d)
    details = details[: env_int("MAX_DETAIL", 80)]
    log.info("detail pages to follow %s", len(details))
    for durl in details:
        try:
            r = live_get(durl, ua=UA, retries=1, verify=False)
        except Exception:
            continue
        if getattr(r, "status_code", 0) != 200:
            continue
        for href in re.findall(r'href="([^"]+)"', r.text or ""):
            full = urljoin(durl, href)
            lowf = full.lower()
            if lowf.endswith(".pdf") or (".pdf" in lowf and not any(ext in lowf for ext in (".jpg",".jpeg",".png",".gif",".webp"))):
                add_url(items, seen, full.split("?")[0], prefer=True)
            elif "jet_download=" in lowf and len(full.split("jet_download=")[-1]) >= 20:
                add_url(items, seen, full.split("?")[0] if ".pdf" in lowf else full, prefer=False)

    for prefix in (
        "justice.gov.et/wp-content/uploads/",
        "www.justice.gov.et/wp-content/uploads/",
        "hopr.gov.et/documents/",
        "www.hopr.gov.et/documents/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 200), match_type="prefix"):
            orig = h.get("original") or ""
            if orig and orig.lower().endswith(".pdf") and not any(x in orig.lower() for x in (".jpg", ".png", ".gif")):
                add_url(items, seen, orig, prefer=True)

    # Prefer real PDFs; deprioritize jet_download (often HTML bounce)
    def rank(x):
        u=x[1].lower()
        if u.endswith('.pdf'): return (0, u)
        if 'jet_download' in u: return (2, u)
        return (1, u)
    items.sort(key=rank)
    out = [(i, u) for i, u, _ in items]
    log.info("catalog %s (pdfs=%s)", len(out), sum(1 for _,u,_ in items if u.lower().endswith('.pdf')))
    return out


def resplit_existing():
    instr = _CORPORA / "et" / "instruments"
    n = 0
    for p in instr.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        docs = rec.get("documents") or []
        if len(text) < 500:
            continue
        if "Filter by Sector" in text[:800]:
            continue
        new_docs = split_custom(text, rec.get("id") or p.stem, rec.get("source_url") or "", None, ART)
        if len(new_docs) > len(docs):
            rec["documents"] = new_docs
            rec["article_count"] = len(new_docs)
            rec["article_extraction_status"] = "ok"
            p.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            n += 1
    log.info("resplit improved %s", n)
    return n


def main():
    setup_log(CC)
    t0 = utcnow()
    qn = quarantine_junk()
    log.info("quarantined %s", qn)
    max_new = env_int("MAX_NEW", 60)
    max_seconds = env_int("MAX_SECONDS", 2400)
    t_start = time.time()
    if env_int("RESPLIT", 1):
        resplit_existing()
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
        # Prefer PDFs; skip pure HTML law pages this deepen
        if "/law/" in url and ".pdf" not in url.lower() and "jet_download" not in url.lower():
            fail += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=200)
        text = got.get("text") or ""
        # Reject MoJ homepage / non-gazette HTML shells
        if "Welcome to Ministry of Justice" in text[:400] or (got.get("method") == "http_html" and ".pdf" not in url.lower() and "NEGARIT" not in text.upper() and "አዋጅ" not in text[:800] and "Proclamation" not in text[:800]):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "html_shell"})
            continue
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if "Filter by Sector" in text[:1000] or (len(text) < 400 and "Proclamations" in text[:200]):
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": "listing_shell"})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_et.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s bytes=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Federal Negarit Gazette (justice.gov.et)",
        source_urls=["https://justice.gov.et/", "https://www.justice.gov.et/en/laws/proclamations/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete",
        notes="Official MoJ proclamation/regulation PDFs. Article splits via Article/አንቀጽ. Not LawEthiopia. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
