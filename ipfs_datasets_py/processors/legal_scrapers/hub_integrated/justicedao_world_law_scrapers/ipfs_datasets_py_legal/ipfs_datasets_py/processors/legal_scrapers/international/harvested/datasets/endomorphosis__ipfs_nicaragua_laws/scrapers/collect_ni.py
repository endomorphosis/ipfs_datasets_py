#!/usr/bin/env python3
"""Nicaragua: Asamblea Nacional legislación / Gaceta (legislacion.asamblea.gob.ni) PDFs + Wayback.

Official only — SILEG/Gacetas.nsf, Normaweb.nsf, legacy /gacetas/ PDFs.
Live TLS often fails; prefer live then Wayback of the same official URL.
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
import re
import sys
import time
import urllib.parse
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import existing_ids, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, fetch_official, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "ni", "Nicaragua", "es"
SOURCE_TYPE = "asamblea_ni"
LICENSE = (
    "Legislación / Gaceta — Asamblea Nacional de Nicaragua (legislacion.asamblea.gob.ni). "
    "Authentic official text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=http://legislacion.asamblea.gob.ni/)"
ART = re.compile(
    r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s+[\d]+[A-Za-zº°o.]?)\b"
)
log = logging.getLogger("ni")

# Prefer leyes / gacetas; deprioritize anexos, listados, simbolos
SKIP_STEM = re.compile(
    r"(?i)(anexo|listado|simbolo|simbolos|diario\s*de\s*debates|fe\s*de\s*errata$)"
)
LEY_HINT = re.compile(r"(?i)(ley|gaceta|constituci|codigo|c[oó]digo|decreto)")


def _norm_url(url: str) -> str:
    url = (url or "").strip().split("#")[0]
    url = re.sub(r"https?://([^/]+):80/", r"http://\1/", url)
    url = url.replace("https://legislacion.asamblea.gob.ni/", "http://legislacion.asamblea.gob.ni/")
    return url


def _file_ident(url: str) -> str:
    """Extract Domino $FILE name or path stem — matches Hub identifier style."""
    raw = unquote(url)
    m = re.search(r"(?i)/\$FILE/([^/?#]+)", raw)
    if m:
        name = m.group(1)
    else:
        name = Path(urlparse(raw).path).name
    name = name.replace("%20", " ").replace("+", " ")
    # Hub used both + and _ encodings; keep a stable-ish stem
    stem = Path(name).stem if name.lower().endswith(".pdf") else name
    stem = stem.strip()[:160]
    if not stem or stem.lower() in ("file", "$file"):
        stem = re.sub(r"\W+", "-", url)[-100:]
    return stem


def discover() -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    cdx_limit = env_int("CDX_LIMIT", 800)

    def add(url: str):
        url = _norm_url(url)
        if "asamblea.gob.ni" not in url.lower():
            return
        low = url.lower()
        if ".pdf" not in low and "$file" not in low:
            return
        # Drop obvious non-instruments
        if any(x in low for x in ("/comision.nsf/", "simbolos", ".jpg", ".png", "favicon")):
            return
        key = re.sub(r"^https?://(www\.)?", "", url.lower()).rstrip("/")
        if key in seen:
            return
        ident = _file_ident(url)
        if SKIP_STEM.search(ident) and not LEY_HINT.search(ident):
            return
        seen.add(key)
        items.append((ident, url))

    prefixes = [
        "legislacion.asamblea.gob.ni/SILEG/Gacetas.nsf/",
        "legislacion.asamblea.gob.ni/SILEG/Iniciativas.nsf/",
        "legislacion.asamblea.gob.ni/normaweb.nsf/",
        "legislacion.asamblea.gob.ni/Normaweb.nsf/",
        "legislacion.asamblea.gob.ni/gacetas/",
        "legislacion.asamblea.gob.ni/SILEG/",
    ]
    per = max(120, cdx_limit // max(1, len(prefixes) - 1))
    for i, prefix in enumerate(prefixes):
        lim = cdx_limit if i == 0 else per
        hits = cdx_urls(
            prefix,
            limit=lim,
            match_type="prefix",
            extra_filters=["mimetype:application/pdf"],
        )
        for h in hits:
            orig = h.get("original") or ""
            if orig:
                add(orig)

    def rank(it: tuple[str, str]):
        ident, url = it
        low = (ident + " " + url).lower()
        score = 0
        if "gacetas.nsf" in low or "/gacetas/" in low:
            score -= 40
        if re.search(r"ley\s*no|ley_", low):
            score -= 30
        if "normaweb" in low and "ley" in low:
            score -= 15
        if SKIP_STEM.search(ident):
            score += 50
        ym = re.search(r"(20\d{2}|19\d{2})", ident)
        if ym:
            score -= int(ym.group(1)) - 1900
        return (score, ident)

    items.sort(key=rank)
    log.info("catalog %s", len(items))
    return items


def seed_done_from_hub(done: set[str]) -> int:
    """Optionally seed skip-set from Hub identifiers file or parquet path."""
    seed = _CORPORA / "ni" / "_hub_seed_ids.json"
    if not seed.exists():
        return 0
    try:
        ids = json.loads(seed.read_text())
        n0 = len(done)
        for i in ids:
            done.add(str(i))
            # also slug forms
            done.add(slug_id(CC, str(i)))
        return len(done) - n0
    except Exception as exc:
        log.info("hub seed fail %s", exc)
        return 0


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 120)
    max_seconds = env_int("MAX_SECONDS", 4500)
    t_start = time.time()
    done = existing_ids(CC)
    seeded = seed_done_from_hub(done)
    if seeded:
        log.info("seeded %s hub ids (done=%s)", seeded, len(done))
    ok = skip = fail = 0
    catalog = discover()
    for ident, url in catalog:
        if max_new and ok >= max_new:
            break
        if time.time() - t_start > max_seconds:
            break
        rid = slug_id(CC, ident)
        # also skip if URL-encoded variant already known
        alt = slug_id(CC, urllib.parse.quote(ident, safe=""))
        if rid in done or alt in done or ident in done:
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
            s = line.strip()
            if len(s) > 18 and not s.lower().startswith("just a moment"):
                title = s[:240]
                break
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
            collector="collect_ni.py",
            article_re=ART,
            extra_meta={"fetch_method": got.get("method")},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s method=%s chars=%s", ident[:70], got.get("method"), len(text))
        else:
            fail += 1
    write_summary(
        CC,
        country=COUNTRY,
        source="Asamblea Nacional de Nicaragua",
        source_urls=["http://legislacion.asamblea.gob.ni/"],
        license_text=LICENSE,
        discovered=len(catalog),
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="catalog-backed incomplete (Wayback of official SILEG/Normaweb/gacetas PDFs)",
        notes=(
            "Official Asamblea legislación PDFs (SILEG Gacetas.nsf / Normaweb / gacetas). "
            "Live TLS often fails; Wayback used. Not vLex. Not legal advice."
        ),
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
