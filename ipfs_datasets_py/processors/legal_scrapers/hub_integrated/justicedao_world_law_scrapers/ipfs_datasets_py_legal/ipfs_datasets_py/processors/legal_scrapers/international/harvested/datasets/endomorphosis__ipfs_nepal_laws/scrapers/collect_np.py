#!/usr/bin/env python3
"""Nepal: lawcommission.gov.np / Nepal Law Commission official acts (HTML/PDF)."""
from __future__ import annotations
import logging, re, sys, time
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "np", "Nepal", "ne"
SOURCE_TYPE = "nepal_law_commission"
LICENSE = (
    "Nepal Law Commission (lawcommission.gov.np). Official texts prevail. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.lawcommission.gov.np/)"
ART = re.compile(r"(?im)^\s*((?:\d+\.\s*|Section\s+\d+|दफा\s*\d+))\b")
log = logging.getLogger("np")


def load_prior_catalog(seen: set) -> list:
    import json
    from common import ROOT
    items = []
    def add_pair(ident, url):
        if not url or url in seen:
            return
        seen.add(url)
        items.append((ident or Path(str(url).split("?")[0]).stem[:140], url))
    for name in ("catalog.jsonl",):
        cat = ROOT / "np" / "raw" / name
        if cat.exists():
            for line in cat.open(encoding="utf-8"):
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                add_pair(row.get("ident") or row.get("identifier"), row.get("url") or row.get("source_url"))
    idx = ROOT / "np" / "index.jsonl"
    if idx.exists():
        for line in idx.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            add_pair(row.get("identifier") or row.get("id"), row.get("source_url") or row.get("url"))
    inst = ROOT / "np" / "instruments"
    if inst.exists():
        for jp in inst.glob("*.json"):
            try:
                row = json.loads(jp.read_text(encoding="utf-8"))
            except Exception:
                continue
            add_pair(row.get("official_identifier") or row.get("identifier") or jp.stem,
                     row.get("source_url"))
    return items


def discover():
    items, seen = [], set()
    # prefer prior catalog when CDX flaky
    prior = load_prior_catalog(seen)
    if len(prior) >= 20:
        log.info("using prior catalog %s (skip fresh CDX this run)", len(prior))
        return prior
    seeds = [
        "https://www.lawcommission.gov.np/en/",
        "https://www.lawcommission.gov.np/np/",
        "https://www.lawcommission.gov.np/en/archives/category/documents/prevailing-law",
        "https://www.lawcommission.gov.np/en/category/prevailing-laws/",
        "https://www.lawcommission.gov.np/en/archives/category/documents",
        "https://www.lawcommission.gov.np/en/archives/category/documents/prevailing-law/statutes-acts",
        "https://www.lawcommission.gov.np/en/archives/category/documents/prevailing-law/rules-and-regulations",
        "https://www.lawcommission.gov.np/en/archives/category/constitution",
        "https://www.lawcommission.gov.np/np/archives/category/documents",
        "https://www.lawcommission.gov.np/en/archives/",
    ]
    for su in seeds:
        try:
            r = live_get(su, ua=UA, verify=False, timeout=(20, 50))
        except Exception as exc:
            log.info("seed fail %s: %s", su, exc)
            continue
        for href in re.findall(r'href="([^"]+)"', r.text or ""):
            full = urljoin(su, href).replace(":80/", "/").replace("http://www.lawcommission.gov.np/", "https://www.lawcommission.gov.np/")
            if "lawcommission.gov.np" not in full:
                continue
            if any(x in full.lower() for x in [".pdf", "/archives/", "/documents/", "prevailing", "act", "statute"]):
                if full in seen:
                    continue
                seen.add(full)
                ident = Path(full.rstrip("/").split("?")[0]).stem[:140] or re.sub(r"\W+", "-", full)[-80:]
                items.append((ident, full))
    for prefix in (
        "www.lawcommission.gov.np/wp-content/uploads/",
        "lawcommission.gov.np/wp-content/uploads/",
        "www.lawcommission.gov.np/en/wp-content/uploads/",
        "www.lawcommission.gov.np/np/wp-content/uploads/",
        "lawcommission.gov.np/en/wp-content/uploads/",
    ):
        for h in cdx_urls(prefix, limit=env_int("CDX_LIMIT", 1200), match_type="prefix",
                          extra_filters=["mimetype:application/pdf"]):
            orig = (h.get("original") or "").replace("http://", "https://").replace(":80/", "/").replace(":80?", "?")
            if not orig or orig in seen:
                continue
            seen.add(orig)
            items.append((Path(orig).stem[:140], orig))
    if not items:
        items = load_prior_catalog(seen)
        log.info("cdx empty — reused prior catalog %s", len(items))
    else:
        cat = Path(__file__).resolve().parents[1] / "np" / "raw" / "catalog.jsonl"
        cat.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        with cat.open("w", encoding="utf-8") as f:
            for ident, url in items:
                f.write(_json.dumps({"ident": ident, "url": url}, ensure_ascii=False) + "\n")
    log.info("catalog %s", len(items))
    return items


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 400)
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
        got = fetch_official(url, ua=UA, verify=False, min_text=200)
        text = got.get("text") or ""
        if got.get("status") != "success":
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error")})
            continue
        # Skip pure index pages
        if text.count("\n") < 5 and len(text) < 500:
            fail += 1
            continue
        title = None
        for line in text.splitlines():
            if len(line.strip()) > 18:
                title = line.strip()[:240]
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_np.py",
            article_re=ART, extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s chars=%s", ident[:60], len(text))
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="Nepal Law Commission",
        source_urls=["https://www.lawcommission.gov.np/"],
        license_text=LICENSE, discovered=ok + skip + fail, fetched=ok, skipped=skip, failed=fail,
        coverage="uploads/archives incomplete",
        notes="Official Nepal Law Commission documents. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
