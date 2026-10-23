#!/usr/bin/env python3
"""Trinidad and Tobago: LRC Digital Law Library + Parliament Acts + laws.gov.tt PDFs.

Official-only (laws.gov.tt / ttparliament.org). Live TTDLL revision downloads +
Parliament wp-content Acts uploads + Wayback/CDX of official PDF prefixes.
Not vLex / commercial aggregators.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary, write_instrument, base_record
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id, first_title

CC, COUNTRY, LANG = "tt", "Trinidad and Tobago", "en"
SOURCE_TYPE = "tt_parliament_laws"
LICENSE = (
    "Parliament of the Republic of Trinidad and Tobago / Law Revision Commission "
    "(ttparliament.org, laws.gov.tt). Authentic official text prevails. Not legal advice."
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "legal-corpora-collector/1.0 (research; source=https://laws.gov.tt/)"
)
# Commonwealth + TT Cap/LRC drafting: "Section 1" / "1. Short title."
ART = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?|"
    r"\d{1,3}[A-Za-z]?\.)(?=\s+(?:\([0-9]+\)|[A-Z\"'“‘]))"
)
log = logging.getLogger("tt")

TTDLL = "https://laws.gov.tt"
HOST_OK = ("laws.gov.tt", "ttparliament.org", "www.ttparliament.org", "www.laws.gov.tt")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/pdf,*/*"})
    s.verify = False
    return s


def _add(items: list, seen: set, ident: str, url: str, title: str | None = None):
    url = (url or "").split("#")[0].strip()
    if not url:
        return
    url = url.replace("http://", "https://").replace(":80/", "/")
    low = url.lower()
    if not any(h in low for h in ("ttparliament.org", "laws.gov.tt")):
        return
    if url in seen:
        return
    seen.add(url)
    ident = (ident or Path(url.split("?")[0]).stem)[:160]
    items.append((ident, url, title))


def discover_ttdll_caps(sess: requests.Session, items: list, seen: set) -> int:
    """Revised Cap Acts from /ttdll-web/revision/list (newest type=act PDF per chapter)."""
    n0 = len(items)
    for off in range(0, env_int("TTDLL_LIST_MAX_OFFSET", 800), 10):
        try:
            rr = sess.get(f"{TTDLL}/ttdll-web/revision/list?offset={off}", timeout=45)
        except Exception as exc:
            log.info("ttdll list offset %s err %s", off, exc)
            break
        if rr.status_code != 200:
            break
        dls = re.findall(r"/ttdll-web/revision/download/(\d+)\?type=(\w+)", rr.text)
        if not dls:
            if off > 0:
                break
            continue
        name_m = re.findall(r">([^<]*Chap\.[^<]+)<", rr.text)
        name = name_m[0].strip() if name_m else f"ttdll-list-{off}"
        acts = [(i, t) for i, t in dls if t == "act"]
        did, typ = acts[0] if acts else dls[0]
        url = f"{TTDLL}/ttdll-web/revision/download/{did}?type={typ}"
        _add(items, seen, f"ttdll-{did}-{typ}", url, name)
    return len(items) - n0


def discover_ttdll_bytitle(sess: requests.Session, items: list, seen: set) -> int:
    """Acts/amendments listed under bytitle alphabet + full bytitle pagination."""
    n0 = len(items)
    max_alpha = env_int("TTDLL_ALPHA_MAX", 4000)

    def harvest(url: str) -> int:
        try:
            rr = sess.get(url, timeout=45)
        except Exception as exc:
            log.info("ttdll bytitle err %s %s", url, exc)
            return 0
        if rr.status_code != 200:
            return 0
        rows = re.findall(
            r'href="(/ttdll-web/revision/download/(\d+)\?type=(\w+))"[^>]*>.*?'
            r"<strong[^>]*>([^<]+)</strong>.*?</a>.*?<td>([^<]*)</td>",
            rr.text,
            re.S,
        )
        added = 0
        for path, did, typ, ref, title in rows:
            if len(items) - n0 >= max_alpha:
                return added
            full = urljoin(TTDLL, path)
            label = (title or "").strip() or (ref or "").strip() or f"ttdll-{did}"
            ident = f"ttdll-{did}-{typ}"
            before = len(seen)
            _add(items, seen, ident, full, label)
            if len(seen) > before:
                added += 1
        return added

    # Full bytitle chronological/title index
    for off in range(0, env_int("TTDLL_BYTITLE_MAX_OFFSET", 600), 30):
        if len(items) - n0 >= max_alpha:
            break
        n = harvest(f"{TTDLL}/ttdll-web/revision/bytitle?offset={off}")
        if off > 0 and n == 0:
            break

    # Alphabet pages (deeper coverage; paginated)
    for letter in "abcdefghijklmnopqrstuvwxyz":
        if len(items) - n0 >= max_alpha:
            break
        for off in range(0, 5000, 30):
            if len(items) - n0 >= max_alpha:
                break
            n = harvest(f"{TTDLL}/ttdll-web/revision/bytitle?q={letter}&offset={off}")
            if off > 0 and n == 0:
                break
            if off == 0 and n == 0:
                break
    return len(items) - n0


def discover_parliament_live(sess: requests.Session, items: list, seen: set) -> int:
    """Scrape Acts of Parliament listing pages for official uploaded Act PDFs."""
    n0 = len(items)
    max_pages = env_int("PARL_MAX_PAGES", 25)
    pub_urls: list[str] = []
    for page in range(1, max_pages + 1):
        url = (
            "https://www.ttparliament.org/publications/acts-of-parliament/"
            if page == 1
            else f"https://www.ttparliament.org/publications/acts-of-parliament/page/{page}/"
        )
        try:
            rr = sess.get(url, timeout=45)
        except Exception as exc:
            log.info("parliament list err %s", exc)
            break
        if rr.status_code != 200:
            break
        found = re.findall(
            r'href="(https://www\.ttparliament\.org/publication/[^"]+/)"',
            rr.text,
        )
        new = [u for u in found if u not in pub_urls]
        if not new and page > 1:
            break
        pub_urls.extend(new)
    log.info("parliament publications listed %s", len(pub_urls))
    for pu in pub_urls:
        if len(items) - n0 >= env_int("PARL_MAX_PDFS", 250):
            break
        try:
            rr = sess.get(pu, timeout=45)
        except Exception:
            continue
        pdfs = re.findall(
            r'href="(https://www\.ttparliament\.org/wp-content/uploads/[^"]+\.pdf)"',
            rr.text,
            re.I,
        )
        # Prefer Act PDFs (aYYYY-NNg.pdf style); skip marriage-policy etc.
        for pdf in pdfs:
            low = pdf.lower()
            stem = Path(pdf.split("?")[0]).stem
            if any(x in low for x in ("brochure", "newsletter", "policy-for-use", "flyer", "form")):
                continue
            if not re.search(r"(^a\d{4}|act|bill|gazette|a\d{4}-\d+)", stem, re.I):
                # still allow if linked as View or Download Act
                if "View or Download Act" not in rr.text and "/acts/" not in low:
                    if not re.search(r"a\d{4}-\d+", stem, re.I):
                        continue
            title = None
            tm = re.search(r"<h1[^>]*>([^<]{5,200})</h1>", rr.text, re.I)
            if tm:
                title = re.sub(r"\s+", " ", tm.group(1)).strip()
            _add(items, seen, stem, pdf, title)
    return len(items) - n0


def discover_cdx(items: list, seen: set) -> int:
    n0 = len(items)
    prefixes = (
        "laws.gov.tt/pdf/",
        "www.laws.gov.tt/pdf/",
        "www.ttparliament.org/wp-content/uploads/",
        "ttparliament.org/wp-content/uploads/",
        "www.ttparliament.org/bills/acts/",
        "ttparliament.org/bills/acts/",
    )
    for prefix in prefixes:
        for h in cdx_urls(
            prefix,
            limit=env_int("CDX_LIMIT", 2000),
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        ):
            orig = h.get("original") or ""
            if not orig or ".pdf" not in orig.lower():
                continue
            low = orig.lower()
            if any(x in low for x in ("brochure", "newsletter", "flyer", "form", "policy-for-use", "favicon")):
                continue
            # parliament uploads: prefer act-like filenames
            if "wp-content/uploads" in low and not re.search(r"/a\d{4}|act|bill", low):
                continue
            _add(items, seen, Path(orig.split("?")[0]).stem[:160], orig)
    return len(items) - n0


def discover():
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    items: list = []
    seen: set = set()
    sess = _session()
    n_cap = discover_ttdll_caps(sess, items, seen)
    n_title = discover_ttdll_bytitle(sess, items, seen)
    n_parl = discover_parliament_live(sess, items, seen)
    n_cdx = discover_cdx(items, seen)
    log.info(
        "catalog total=%s ttdll_cap=%s ttdll_bytitle=%s parliament=%s cdx=%s",
        len(items),
        n_cap,
        n_title,
        n_parl,
        n_cdx,
    )
    return items


def reextract_existing() -> int:
    """Re-split articles on existing instruments with improved Cap-style ART."""
    root = Path(os.environ.get("LEGAL_CORPORA_ROOT", "{_CORPORA}")) / CC / "instruments"
    if not root.is_dir():
        return 0
    improved = 0
    for path in sorted(root.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if len(text) < 120:
            continue
        old_n = int(rec.get("article_count") or len(rec.get("documents") or []) or 0)
        from world_lib import split_custom

        docs = split_custom(text, rec.get("id") or path.stem, rec.get("source_url") or "", rec.get("date"), ART)
        new_n = len(docs)
        if new_n <= old_n:
            continue
        rec["documents"] = docs
        rec["article_count"] = new_n
        rec["article_extraction_status"] = "ok" if new_n else "missing"
        meta = rec.get("metadata") or {}
        meta["article_reextract"] = "collect_tt_cap_style"
        rec["metadata"] = meta
        write_instrument(CC, rec)
        improved += 1
        log.info("reextract %s %s -> %s", path.name, old_n, new_n)
    return improved


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 200)
    max_seconds = env_int("MAX_SECONDS", 3600)
    t_start = time.time()
    done = existing_ids(CC)
    ok = skip = fail = 0
    catalog = discover()
    for ident, url, title in catalog:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, min_text=120)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        if not title:
            title = first_title(text, ident)
        if save_instrument(
            cc=CC,
            country=COUNTRY,
            language=LANG,
            ident=ident,
            title=title or ident,
            text=text,
            source_url=got.get("source_url") or url,
            source_type=SOURCE_TYPE,
            license_text=LICENSE,
            collector="collect_tt.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    rex = reextract_existing()
    write_summary(
        CC,
        country=COUNTRY,
        source="TT Parliament / laws.gov.tt LRC Digital Law Library",
        source_urls=[
            "https://www.ttparliament.org/",
            "https://laws.gov.tt/",
            "https://laws.gov.tt/ttdll-web/revision/list",
        ],
        license_text=LICENSE,
        discovered=ok + skip + fail,
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete (TTDLL live + Parliament uploads + Wayback official PDFs)",
        notes=(
            f"Official Parliament Acts and Law Revision Commission PDFs. "
            f"reextract_improved={rex}. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s reextract=%s", ok, skip, fail, rex)


if __name__ == "__main__":
    main()
