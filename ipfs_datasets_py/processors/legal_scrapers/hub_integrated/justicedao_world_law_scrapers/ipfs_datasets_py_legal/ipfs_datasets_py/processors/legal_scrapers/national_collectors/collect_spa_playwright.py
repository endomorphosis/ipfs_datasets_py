#!/usr/bin/env python3
"""Playwright fallback for Angular/OutSystems gazette shells (LU, PT, SI)."""
from __future__ import annotations
import json, logging, re, sys, time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
from collect_blocked_archives import SPECS, ident_from_url, extract_title, date_from_url_or_ts, setup_log

log = logging.getLogger("spa_pw")
MIN_TEXT = 400

def load_failed_urls(cc: str, limit: int = 40) -> list[str]:
    p = ROOT / cc / "failures.jsonl"
    urls, seen = [], set()
    if p.exists():
        for line in p.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            u = row.get("source_url") or ""
            if u and u not in seen:
                seen.add(u); urls.append(u)
    for s in (SPECS.get(cc) or {}).get("seeds") or []:
        if s not in seen:
            seen.add(s); urls.append(s)
    extra = {
        "lu": [
            "https://legilux.public.lu/eli/etat/leg/code/constitution",
            "http://data.legilux.public.lu/eli/etat/leg/code/constitution/jo",
            "https://legilux.public.lu/eli/etat/leg/code/penal",
            "https://legilux.public.lu/eli/etat/leg/code/civil",
            "https://data.legilux.public.lu/eli/etat/leg/loi/2020/03/24/a185/jo",
        ],
        "pt": [
            "https://dre.pt/dre/detalhe/decreto-aprovacao-constituicao/1976-480623",
            "https://diariodarepublica.pt/dr/detalhe/lei/1-2024-840011226",
            "https://data.dre.pt/eli/dec-lei/47344/1966/p/cons/20170803/pt/html",
        ],
        "si": [
            "https://www.pisrs.si/Pis.web/pregledPredpisa?id=USTA1",
            "https://www.pisrs.si/Pis.web/pregledPredpisa?id=ZAKO1",
            "https://www.pisrs.si/Pis.web/pregledPredpisa?id=ZAKO33",
        ],
    }
    for u in extra.get(cc, []):
        if u not in seen:
            seen.add(u); urls.append(u)
    return urls[:limit]


def render(url: str, timeout_ms: int = 45000) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(1500)
            html = page.content()
            title = page.title() or ""
            text = page.inner_text("body") if page.query_selector("body") else ""
            final = page.url
        except Exception as exc:
            browser.close()
            return {"status": "error", "error": repr(exc), "url": url}
        browser.close()
        return {"status": "success", "html": html, "title": title, "text": text, "final_url": final, "url": url}


def harvest(cc: str) -> None:
    spec = SPECS[cc]
    setup_log(cc)
    done = existing_ids(cc)
    urls = load_failed_urls(cc, 35)
    ok = skip = fail = 0
    notes = [f"playwright chromium fallback for SPA {cc}", f"urls={len(urls)}"]
    for url in urls:
        ident = ident_from_url(cc, url)
        rid = slug_id(cc, ident)
        if rid in done:
            skip += 1; continue
        time.sleep(0.4)
        res = render(url)
        if res.get("status") != "success":
            fail += 1
            log_failure(cc, {"identifier": ident, "source_url": url, "status": "failed",
                             "reason": res.get("error"), "method_used": "playwright"})
            continue
        text = (res.get("text") or "").strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        if len(text) < MIN_TEXT:
            fail += 1
            log_failure(cc, {"identifier": ident, "source_url": url, "status": "failed",
                             "reason": f"playwright_short_{len(text)}", "method_used": "playwright"})
            continue
        title = res.get("title") or extract_title(res.get("html") or "", ident)
        rec = base_record(
            cc=cc, country=spec["country"], language=spec["lang"], ident=ident,
            title=title, text=text, source_url=url, source_type=spec["source_type"],
            license_text=spec["license"], collector=f"{cc}-playwright-spa",
            eli=url if "/eli/" in url else None, date=date_from_url_or_ts(url, ""),
            official_identifier=ident, document_type="statute",
            law_status="unknown", is_current=None,
            extra_meta={"method_used": "playwright",
                        "discovery": {"method": "playwright_spa", "seed_url": url},
                        "text_extraction": {"source": "official", "backend": "playwright"}},
        )
        write_instrument(cc, rec); done.add(rid); ok += 1
        log.info("%s playwright ok %s tlen=%s", cc, ident[:60], len(text))
    write_summary(cc, country=spec["country"], source="playwright SPA fallback + archives",
                  source_urls=spec["cdx"] + spec.get("seeds", []), license_text=spec["license"],
                  discovered=len(urls), fetched=ok, skipped=skip, failed=fail,
                  coverage="shard" if ok else "empty CDX or SPA chrome",
                  notes="\n".join(notes), last_run=utcnow())
    log.info("%s playwright done ok=%s fail=%s skip=%s", cc, ok, fail, skip)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    targets = [a for a in sys.argv[1:] if a in SPECS] or ["lu", "pt", "si"]
    for cc in targets:
        harvest(cc)
