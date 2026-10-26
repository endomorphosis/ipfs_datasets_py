#!/usr/bin/env python3
"""Fiji: laws.gov.fj LawsAsMade PDF downloads + Wayback of official URLs."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "fj", "Fiji", "en"
SOURCE_TYPE = "laws_gov_fj"
LICENSE = (
    "Laws of Fiji / Government of Fiji (laws.gov.fj). "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.laws.gov.fj/)"
ART = re.compile(r"(?im)^\s*((?:Section|Article|Art\.?)\s+[0-9]+)\b")
log = logging.getLogger("fj")


def load_prior_catalog(seen: set) -> list:
    """Resume from raw/catalog.jsonl, index.jsonl, or instrument source_urls when CDX fails."""
    import json
    from common import ROOT
    items = []
    def add_pair(ident, url):
        if not url or url in seen:
            return
        seen.add(url)
        items.append((ident or Path(url.split("?")[0]).stem[:160], url))
    cat = ROOT / "fj" / "raw" / "catalog.jsonl"
    if cat.exists():
        for line in cat.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            add_pair(row.get("ident") or row.get("identifier"), row.get("url") or row.get("source_url"))
    idx = ROOT / "fj" / "index.jsonl"
    if idx.exists():
        for line in idx.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            add_pair(row.get("identifier") or row.get("id"), row.get("source_url") or row.get("url"))
    inst = ROOT / "fj" / "instruments"
    if inst.exists():
        for jp in inst.glob("*.json"):
            try:
                row = json.loads(jp.read_text(encoding="utf-8"))
            except Exception:
                continue
            add_pair(row.get("official_identifier") or row.get("identifier") or jp.stem,
                     row.get("source_url") or (row.get("metadata") or {}).get("source_url"))
    return items


def discover():
    items, seen = [], set()
    def add(url):
        from urllib.parse import unquote, urlparse, parse_qs
        url = url.split("#")[0].replace("http://", "https://").replace(":80/", "/")
        low = url.lower()
        if "laws.gov.fj" not in low:
            return
        if url in seen:
            return
        # Accept LawsAsMade downloadfile, Acts PDFs, ConsolidatedActs, SubsidiaryLegislation PDFs
        ok = (
            "downloadfile" in low
            or low.endswith(".pdf")
            or "/acts/" in low
            or "lawsasmade" in low
            or "consolidated" in low
            or "subsidiary" in low
            or "actasmade" in low
        )
        if not ok:
            return
        # Prefer PDF / downloadfile endpoints over HTML act pages
        if ("/acts/" in low or "displayact" in low) and "download" not in low and ".pdf" not in low:
            return
        qs = parse_qs(urlparse(url).query)
        fname = (qs.get("fileName") or qs.get("filename") or qs.get("file") or [None])[0]
        if fname:
            ident = Path(unquote(fname)).stem[:160]
        else:
            ident = Path(unquote(url.split("?")[0])).stem[:160] or url.rstrip("/").rsplit("/", 1)[-1][:160]
        ident = re.sub(r"[^\w.\-]+", "-", ident).strip("-")[:160] or "act"
        key = ident.lower()
        if key in seen:
            return
        seen.add(url)
        seen.add(key)
        items.append((f"fj-{ident}", url))
    for prefix in (
        "www.laws.gov.fj/LawsAsMade/downloadfile/",
        "laws.gov.fj/LawsAsMade/downloadfile/",
        "www.laws.gov.fj/LawsAsMade/DownloadFile/",
        "laws.gov.fj/LawsAsMade/DownloadFile/",
        "www.laws.gov.fj/LawsAsMade/",
        "laws.gov.fj/LawsAsMade/",
        "www.laws.gov.fj/Acts/",
        "laws.gov.fj/Acts/",
        "www.laws.gov.fj/ConsolidatedActs/",
        "laws.gov.fj/ConsolidatedActs/",
        "www.laws.gov.fj/SubsidiaryLegislation/",
        "laws.gov.fj/SubsidiaryLegislation/",
        "www.laws.gov.fj/ActsAsMade/",
        "laws.gov.fj/ActsAsMade/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 1500), match_type="prefix"):
            orig = h.get("original") or ""
            if not orig:
                continue
            low = orig.lower()
            if "downloadfile" in low or low.endswith(".pdf") or "lawsasmade" in low or "consolidated" in low or "subsidiary" in low or "actasmade" in low:
                add(orig)
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 1200), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = h.get("original") or ""
            if orig:
                add(orig)
    if not items:
        items = load_prior_catalog(seen)
        log.info("cdx empty — reused prior catalog %s", len(items))
    else:
        # persist for idempotent resume when CDX is flaky
        cat = Path(__file__).resolve().parents[1] / "fj" / "raw" / "catalog.jsonl"
        cat.parent.mkdir(parents=True, exist_ok=True)
        with cat.open("w", encoding="utf-8") as f:
            for ident, url in items:
                f.write(__import__("json").dumps({"ident": ident, "url": url}, ensure_ascii=False) + "\n")
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 500)
    max_seconds = env_int("MAX_SECONDS", 7200)
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
        got = fetch_official(url, ua=UA, verify=False, min_text=150)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_fj.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="laws.gov.fj",
        source_urls=["https://www.laws.gov.fj/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete (LawsAsMade downloadfile via Wayback)",
        notes="Official Fiji laws PDFs. Live download endpoints often 404; Wayback of official URLs used. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
