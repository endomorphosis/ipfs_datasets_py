#!/usr/bin/env python3
"""Hungary: NJT official ELI year listings (njt.jog.gov.hu)."""
from __future__ import annotations
import json, logging, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "hu", "Hungary", "njt"
LICENSE = "Nemzeti Jogszabálytár official ELI (njt.jog.gov.hu). Official consolidations; reuse per NJT / jogszabálytár terms."
UA = DEFAULT_UA + " source=https://njt.jog.gov.hu/"
BASE = "https://njt.jog.gov.hu"
# year listing HTML is server-rendered with relative eli/TYPE/year/n links even though the act body is Angular
TYPES = ("TV", "R", "KEH", "JPE", "H", "KGY")
log = logging.getLogger("hu")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def year_elis(dtype: str, year: int) -> list[str]:
    url = f"{BASE}/eli/{dtype}/{year}"
    r = http_get(url, ua=UA, sleep=0.3, retries=2, headers={"Accept": "text/html"})
    if r.status_code != 200:
        return []
    found = re.findall(rf"eli/{dtype}/{year}/(\d+)", r.text)
    return sorted({f"{BASE}/eli/{dtype}/{year}/{n}" for n in found})


def fetch_one(eli: str, done: set[str]) -> str:
    ident = eli.split("/eli/", 1)[-1].replace("/", "-")
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    text = title = ""
    src = eli
    # try print / ajax / html
    for url, method, kwargs in (
        (eli, "GET", {"headers": {"Accept": "text/html"}}),
        (eli + "/xml", "GET", {"headers": {"Accept": "application/xml, text/xml, text/html"}}),
        (f"{BASE}/ajax/njtGetBlock.json", "POST", {"json": {"eli": eli.split("/eli/", 1)[-1]}, "headers": {"Accept": "application/json", "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}}),
    ):
        if method == "GET":
            r = http_get(url, ua=UA, sleep=0.4, retries=2, headers=kwargs.get("headers"))
        else:
            try:
                time.sleep(0.4)
                r = get_session(UA).post(url, timeout=(20, 60), json=kwargs.get("json"), headers=kwargs.get("headers"))
            except Exception:
                continue
        if getattr(r, "status_code", 0) != 200 or not r.content:
            continue
        raw = r.content.decode("utf-8", "replace")
        if raw.lstrip().startswith("{") or raw.lstrip().startswith("["):
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
            blob = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
            # common keys
            if isinstance(data, dict):
                title = data.get("title") or data.get("nev") or data.get("name") or title
                blob = data.get("html") or data.get("text") or data.get("content") or blob
            text = html_to_text(str(blob))
            src = url
        else:
            text = html_to_text(raw)
            m = re.search(r"<title>([^<]+)</title>", raw, re.I)
            title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ident
            src = url
        # Angular chrome only
        if text and len(text) > 200 and "njtAppX" not in raw[:500]:
            break
        if text and len(text) > 800 and "jogszabály" in text.lower():
            break
        text = ""
    if not text or len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": eli, "status": "failed", "reason": "spa_no_text"})
        return "fail"
    rec = base_record(
        cc=CC, country=COUNTRY, language="hu", ident=ident, title=title or ident, text=text,
        source_url=src, source_type=SOURCE_TYPE, license_text=LICENSE, collector="hu-njt-eli",
        eli=eli, date=None, official_identifier=ident, document_type="statute",
        law_status="current", is_current=True,
        extra_meta={"discovery": {"method": "njt_eli_year"}},
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup(); t0 = utcnow()
    elis = []
    seen = set()
    for dtype in TYPES:
        start = 1989 if dtype == "TV" else 1990
        for year in range(start, 2027):
            found = year_elis(dtype, year)
            for e in found:
                if e not in seen:
                    seen.add(e); elis.append(e); append_catalog(CC, {"eli": e})
            if year % 10 == 0:
                log.info("%s %s catalog=%s", dtype, year, len(elis))
    log.info("discovered %s", len(elis))
    done = existing_ids(CC)
    ok = skip = fail = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(fetch_one, e, done) for e in elis]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            if n % 80 == 0:
                log.info("progress %s/%s ok=%s fail=%s", n, len(elis), ok, fail)
                write_summary(CC, country=COUNTRY, source="NJT ELI",
                              source_urls=["https://njt.jog.gov.hu/", "https://njt.jog.gov.hu/eli/urisemak"],
                              license_text=LICENSE, discovered=len(elis), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes="ELI year listings", last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="Nemzeti Jogszabálytár (njt.jog.gov.hu) ELI",
                  source_urls=["https://njt.jog.gov.hu/", "https://njt.jog.gov.hu/eli/urisemak"],
                  license_text=LICENSE, discovered=len(elis), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if elis and fail == 0 else "catalog-backed incomplete",
                  notes="Official ELI year listings are HTML-prerendered. Act bodies are an Angular SPA; texts fetched when ajax/HTML yields non-chrome content.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s fail=%s", len(elis), ok, fail)


if __name__ == "__main__":
    main()
