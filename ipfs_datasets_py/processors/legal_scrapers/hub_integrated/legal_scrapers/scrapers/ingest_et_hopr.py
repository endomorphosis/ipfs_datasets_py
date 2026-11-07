#!/usr/bin/env python3
"""Ingest hopr.gov.et proclamation/regulation PDFs from Wayback CDX list."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import logging, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary, ROOT
from world_lib import env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "et", "Ethiopia", "am"
SOURCE_TYPE = "negarit_gazette"
LICENSE = (
    "Federal Negarit Gazette of the Federal Democratic Republic of Ethiopia as published "
    "via justice.gov.et / hopr.gov.et. Authentic gazette text prevails. Not legal advice. "
    "Not LawEthiopia commercial archive."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.hopr.gov.et/)"
ART = re.compile(r"(?im)^\s*((?:Article|Art\.?|ARTICLE|አንቀጽ)\s*[0-9፩-፼]+[A-Za-z]?)\b")
URLS = Path(str(_SCRAPERS) + "/logs/et_hopr_urls.txt")
MIN_TEXT = 200
log = logging.getLogger("et_hopr")


def ident_of(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    name = re.sub(r"[^\w.\-]+", "-", name, flags=re.U).strip("-")[:140]
    return name or "hopr-doc"


def main() -> None:
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 30)
    max_seconds = env_int("MAX_SECONDS", 3600)
    target = env_int("TARGET_LAWS", 100)
    done = existing_ids(CC)
    urls = [u.strip() for u in URLS.read_text().splitlines() if u.strip()]
    log.info("start candidates=%s ids=%s target=%s", len(urls), len(done), target)
    ok = skip = fail = 0
    t_start = time.time()
    corpus = lambda: sum(1 for _ in (ROOT / CC / "instruments").glob("*.json"))
    laws0 = corpus()
    stems = {ident_of(u).lower() for u in []}
    # existing stems from corpus
    for p in (ROOT / CC / "instruments").glob("*.json"):
        stems.add(p.stem.lower().replace("et-", "", 1))

    for url in urls:
        if ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        if corpus() >= target and ok >= 1:
            log.info("target reached %s", corpus())
            break
        ident = ident_of(url)
        rid = slug_id(CC, ident)
        if rid in done or ident.lower() in stems:
            skip += 1
            continue
        got = fetch_official(url, ua=UA, verify=False, wayback=False, min_text=MIN_TEXT)
        text = got.get("text") or ""
        if len(text) < MIN_TEXT:
            got2 = fetch_official(url, ua=UA, verify=False, wayback=True, min_text=MIN_TEXT)
            if len(got2.get("text") or "") > len(text):
                got, text = got2, got2.get("text") or ""
        if len(text) < MIN_TEXT:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": got.get("error") or "short", "portal": "hopr"})
            continue
        # skip HTML shells / site chrome
        if "Filter by Sector" in text[:1500] or len(text) < 400:
            fail += 1
            continue
        title = None
        for line in text.splitlines():
            s = line.strip()
            if 12 <= len(s) <= 240:
                title = s
                break
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or ident, text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE,
            collector="ingest_et_hopr.py", article_re=ART,
            extra_meta={"fetch_method": got.get("method"), "discovery": "wayback_cdx_hopr"},
        ):
            ok += 1
            done.add(rid)
            stems.add(ident.lower())
            log.info("ok %s method=%s corpus=%s chars=%s", ident[:70], got.get("method"), corpus(), len(text))
        else:
            fail += 1
        time.sleep(0.3)

    laws = corpus()
    write_summary(
        CC, country=COUNTRY, source="Federal Negarit / hopr.gov.et",
        source_urls=["https://justice.gov.et/", "https://www.hopr.gov.et/"],
        license_text=LICENSE, discovered=len(urls), fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete",
        notes=f"hopr CDX ingest. Before {laws0} after {laws}. Started {t0}.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s corpus=%s->%s", ok, skip, fail, laws0, laws)
    print({"ok": ok, "skip": skip, "fail": fail, "laws0": laws0, "laws": laws})


if __name__ == "__main__":
    main()
