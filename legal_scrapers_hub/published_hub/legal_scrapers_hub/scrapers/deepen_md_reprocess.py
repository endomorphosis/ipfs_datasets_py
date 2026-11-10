#!/usr/bin/env python3
"""Re-fetch Moldova legis.md downloadpdf instruments with proper PDF text extract.
Quarantines prior wayback_html/raw-PDF junk. No WAF bypass. No HF upload.
"""
from __future__ import annotations
import json, logging, re, shutil, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "md", "Moldova", "ro"
SOURCE_TYPE = "legis_md"
LICENSE = (
    "Official State Register of Legal Acts of the Republic of Moldova (legis.md). "
    "Authentic register text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.legis.md/)"
ART = re.compile(r"(?im)^\s*((?:Articolul|Art(?:icolul)?\.?)\s*[0-9]+(?:\^[0-9]+)?[a-zA-ZăâîșțĂÂÎȘȚ°ºª-]*|\d{1,3}(?:\^\d+)?)(?:\.|\b)")
log = logging.getLogger("md_deepen")

JUNK_MARKERS = ("%PDF", "endobj", "startxref", "/Type /Page", "cm /I1 Do")


def is_junk_text(text: str) -> bool:
    if not text or len(text) < 80:
        return True
    head = text[:800]
    if any(m in head for m in JUNK_MARKERS):
        return True
    # mostly non-printable / replacement
    bad = sum(1 for c in head if ord(c) < 9 or c == "\ufffd")
    if bad > 40:
        return True
    return False


def quarantine_junk() -> list[str]:
    instr = ROOT / CC / "instruments"
    bak = ROOT / CC / "instruments_junk_wayback_html"
    bak.mkdir(parents=True, exist_ok=True)
    urls = []
    for p in sorted(instr.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        method = ((rec.get("metadata") or {}).get("fetch_method") or "")
        url = rec.get("source_url") or ""
        if method == "wayback_html" or is_junk_text(text) or "downloadpdf" in url:
            if url and "downloadpdf" in url:
                urls.append(url.split("#")[0].replace("http://", "https://"))
            dest = bak / p.name
            if dest.exists():
                dest.unlink()
            shutil.move(str(p), str(dest))
            log.info("quarantine %s", p.name)
    # rebuild index from remaining
    index = ROOT / CC / "index.jsonl"
    remain = []
    for p in sorted(instr.glob("*.json")):
        try:
            remain.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    with index.open("w", encoding="utf-8") as f:
        for rec in remain:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return list(dict.fromkeys(urls))


def discover_downloadpdf(seed_urls: list[str]) -> list[tuple[str, str]]:
    items, seen = [], set()

    def add(url: str):
        url = url.split("#")[0].replace("http://", "https://")
        url = url.replace(":80/", "/")
        if "downloadpdf" not in url.lower():
            return
        if url in seen:
            return
        m = re.search(r"downloadpdf/(\d+)", url, re.I)
        ident = f"cautare-downloadpdf-{m.group(1)}" if m else re.sub(r"^https?://[^/]+/", "", url).replace("/", "-")[:160]
        seen.add(url)
        items.append((ident, url))

    for u in seed_urls:
        add(u)
    for prefix in (
        "www.legis.md/cautare/downloadpdf/",
        "legis.md/cautare/downloadpdf/",
        "www.legis.md:80/cautare/downloadpdf/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 400), match_type="prefix"):
            orig = (h.get("original") or "").strip()
            if orig:
                add(orig)
    log.info("catalog downloadpdf=%s", len(items))
    return items


def main():
    setup_log(CC, "md_deepen")
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 120)
    max_seconds = env_int("MAX_SECONDS", 3600)
    seeds = quarantine_junk()
    log.info("seed urls from quarantine=%s", len(seeds))
    # existing good ids
    from common import existing_ids
    done = existing_ids(CC)
    ok = skip = fail = 0
    t_start = time.time()
    for ident, url in discover_downloadpdf(seeds):
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, min_text=150)
        text = got.get("text") or ""
        if got.get("status") != "success" or is_junk_text(text):
            fail += 1
            log_failure(CC, {
                "identifier": ident,
                "source_url": url,
                "reason": got.get("error") or "junk_text",
                "method": got.get("method"),
            })
            continue
        title = None
        for line in text.splitlines():
            s = line.strip()
            if len(s) > 18 and not s.startswith("%"):
                title = s[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_md.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method"), "deepen": "pdf_reprocess"},
        ):
            ok += 1
            done.add(rid)
            n_docs = 0
            # recount from disk
            p = ROOT / CC / "instruments" / f"{rid}.json"
            if p.exists():
                n_docs = len(json.loads(p.read_text()).get("documents") or [])
            log.info("ok %s method=%s chars=%s arts=%s", ident[:70], got.get("method"), len(text), n_docs)
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="legis.md State Register",
        source_urls=["https://www.legis.md/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (Wayback of official legis.md downloadpdf; live Cloudflare)",
        notes="Deepen: re-extracted PDF text via Wayback; junk wayback_html quarantined. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
