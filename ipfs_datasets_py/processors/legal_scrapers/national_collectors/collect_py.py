#!/usr/bin/env python3
"""Paraguay: BACN leyes HTML (.entry-content full text; descarga PDFs are CF HTML shells)."""
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
from urllib.parse import unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bs4 import BeautifulSoup
from common import existing_ids, http_get, log_failure, utcnow, write_summary
from world_lib import cdx_urls, env_int, live_get, save_instrument, setup_log, slug_id

CC, COUNTRY, LANG = "py", "Paraguay", "es"
SOURCE_TYPE = "bacn_congreso"
LICENSE = (
    "Official texts of laws of the Republic of Paraguay as published by the "
    "Biblioteca y Archivo del Congreso Nacional (bacn.gov.py). Gaceta Oficial / "
    "authentic congressional text prevails. Not legal advice."
)
UA = "legal-corpora-collector/1.0 (research; source=https://www.bacn.gov.py/leyes-paraguayas)"
ART = re.compile(r"(?im)^\s*((?:Art(?:[íi]culo|\.|iculo)?|ART[IÍ]CULO)\s*[\d]+[º°o.]?)\b")
LIST = "https://www.bacn.gov.py/leyes-paraguayas"
SITEMAP = "https://www.bacn.gov.py/sitemap.xml"
log = logging.getLogger("py")


def discover() -> list[tuple[str, str]]:
    items, seen = [], set()

    def add(ident, url):
        ident = str(ident)
        if ident in seen:
            return
        seen.add(ident)
        url = (url or "").replace("http://", "https://").replace("https://www.bacn.gov.py:80/", "https://www.bacn.gov.py/")
        items.append((ident, url.split("#")[0]))

    try:
        r = live_get(SITEMAP, ua=UA, retries=2)
        if r.status_code == 200 and r.content:
            raw = r.content.decode("utf-8", "replace")
            for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", raw):
                loc = unquote(loc.strip())
                m = re.search(r"https?://(?:www\.)?bacn\.gov\.py/leyes-paraguayas/(\d+)/", loc)
                if m:
                    add(m.group(1), loc.replace("http://", "https://"))
            log.info("sitemap leyes %s", len(items))
    except Exception as exc:
        log.info("sitemap err %s", exc)

    for url in (LIST, "https://www.bacn.gov.py/ultimas-leyes-publicadas", "https://www.bacn.gov.py/leyes-mas-solicitadas"):
        try:
            r = http_get(url, ua=UA, sleep=0.2)
            if r.status_code != 200:
                continue
            for href in re.findall(r'href="(https://www\.bacn\.gov\.py/leyes-paraguayas/\d+/[^"]+)"', r.text or ""):
                m = re.search(r"/leyes-paraguayas/(\d+)/", href)
                if m:
                    add(m.group(1), href)
        except Exception as exc:
            log.info("list err %s %s", url, exc)

    for h in cdx_urls("bacn.gov.py/leyes-paraguayas/", limit=env_int("CDX_LIMIT", 300), match_type="prefix"):
        orig = (h.get("original") or "").split("#")[0]
        m = re.search(r"/leyes-paraguayas/(\d+)/", orig)
        if m and ".pdf" not in orig.lower():
            add(m.group(1), orig.replace("http://", "https://").replace(":80/", "/"))

    items.sort(key=lambda x: -int(x[0]) if x[0].isdigit() else 0)
    log.info("catalog %s", len(items))
    return items


def extract_bacn_body(html: str) -> tuple[str, str | None]:
    """Return (text, title) from BACN law page; prefer .entry-content."""
    if not html or "Página no encontrada" in html:
        return "", None
    soup = BeautifulSoup(html, "html.parser")
    title = None
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        title = og["content"].strip()[:240]
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()[:240]
    node = None
    for sel in (".entry-content", ".post-content", ".td-post-content", "article", "#content"):
        found = soup.select(sel)
        if found:
            node = found[0]
            break
    if node is None:
        return "", title
    # drop nav/noise tags inside
    for bad in node.select("script, style, iframe, nav, .sharedaddy, .jp-relatedposts"):
        bad.decompose()
    text = node.get_text("\n", strip=True)
    # strip leading chrome before LEY / Art
    lines = text.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if re.search(r"^(LEY\s+N|Art(?:[íi]culo|\.)?\s+\d+|EL CONGRESO)", ln, re.I):
            start = i
            break
        if i > 40:
            break
    text = "\n".join(lines[start:]).strip()
    # drop trailing site chrome
    cut_markers = ("Libros:", "Dinapi:", "Agenda:", "Semana de los pueblos")
    for marker in cut_markers:
        idx = text.find(marker)
        if idx > 500:
            text = text[:idx].strip()
    return text, title


def main():
    setup_log(CC)
    t0 = utcnow()
    max_new = env_int("MAX_NEW", 120)
    max_seconds = env_int("MAX_SECONDS", 3600)
    refresh_stubs = env_int("REFRESH_STUBS", 1)
    min_text = env_int("MIN_TEXT", 400)
    t_start = time.time()
    done = existing_ids(CC)
    stub_ids = set()
    if refresh_stubs:
        import json
        instr = Path(str(_CORPORA) + "/py/instruments")
        for p in instr.glob("*.json"):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if len(rec.get("text") or "") < 800:
                stub_ids.add(rec.get("id") or p.stem)
                done.discard(rec.get("id") or p.stem)
        log.info("refresh stubs %s", len(stub_ids))

    ok = skip = fail = 0
    items = discover()
    for ident, url in items:
        if max_new and ok >= max_new:
            break
        if max_seconds and (time.time() - t_start) > max_seconds:
            break
        rid = slug_id(CC, ident)
        if rid in done:
            skip += 1
            continue
        try:
            r = live_get(url, ua=UA, retries=2)
        except Exception as exc:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": f"live:{exc}"})
            continue
        if r.status_code != 200:
            fail += 1
            log_failure(CC, {"identifier": ident, "source_url": url, "reason": f"http_{r.status_code}"})
            continue
        text, title = extract_bacn_body(r.text or "")
        if len(text) < min_text:
            # wayback of same official URL
            from world_lib import fetch_official
            got = fetch_official(url, ua=UA, min_text=min_text, wayback=True)
            # re-extract if wayback returned HTML
            if got.get("status") == "success" and got.get("content"):
                raw = got["content"]
                html = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else (got.get("text") or "")
                if "<" in html[:500]:
                    text2, title2 = extract_bacn_body(html)
                    if len(text2) >= len(text):
                        text, title = text2, title2 or title
                        url = got.get("source_url") or url
            if len(text) < min_text:
                fail += 1
                log_failure(CC, {"identifier": ident, "source_url": url, "reason": f"short_{len(text)}"})
                continue
        if save_instrument(
            cc=CC, country=COUNTRY, language=LANG, ident=ident,
            title=title or f"Ley BACN {ident}", text=text, source_url=url,
            source_type=SOURCE_TYPE, license_text=LICENSE, collector="collect_py.py",
            article_re=ART, extra_meta={"fetch_method": "http_html_entry_content"},
        ):
            ok += 1
            done.add(rid)
            log.info("ok %s bytes=%s arts_hint stub=%s", ident, len(text), rid in stub_ids)
        else:
            fail += 1
    write_summary(
        CC, country=COUNTRY, source="BACN leyes paraguayas",
        source_urls=["https://www.bacn.gov.py/leyes-paraguayas", SITEMAP],
        license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
        coverage="catalog-backed incomplete",
        notes="Official BACN HTML .entry-content (full body). Sitemap catalog. Not legal advice.",
        last_run=t0,
    )
    log.info("done ok=%s skip=%s fail=%s", ok, skip, fail)


if __name__ == "__main__":
    main()
