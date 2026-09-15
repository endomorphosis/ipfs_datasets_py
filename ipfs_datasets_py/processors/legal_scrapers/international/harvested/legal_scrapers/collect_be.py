#!/usr/bin/env python3
"""Belgium: official Justel ELI year listings (HTTP fallback when HTTPS drops)."""
from __future__ import annotations
import logging, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "be", "Belgium", "justel"
LICENSE = (
    "Moniteur belge / Belgisch Staatsblad official publications. Justel consolidations "
    "are informational (not authentic). Reuse of public sector information; see "
    "https://www.ejustice.just.fgov.be/ and /img_2024/pdf/GebruiksvoorwaardenFR.pdf"
)
UA = DEFAULT_UA + " source=https://www.ejustice.just.fgov.be/eli/"
HOSTS = (
    "https://www.ejustice.just.fgov.be",
    "http://www.ejustice.just.fgov.be",
)
# French + Dutch document types as published on ELI year indexes
TYPES = ("loi", "wet", "decret", "decreet", "ordonnance", "ordonnantie", "arrete", "besluit", "constitution", "grondwet")
log = logging.getLogger("be")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def get_html(path_or_url: str, retries: int = 4):
    """GET with HTTPS then HTTP fallback; skip TSPD shells."""
    urls = []
    if path_or_url.startswith("http"):
        urls.append(path_or_url)
        if path_or_url.startswith("https://"):
            urls.append("http://" + path_or_url[len("https://"):])
        elif path_or_url.startswith("http://"):
            urls.append("https://" + path_or_url[len("http://"):])
    else:
        p = path_or_url if path_or_url.startswith("/") else "/" + path_or_url
        urls = [h + p for h in HOSTS]
    last = None
    for attempt in range(1, retries + 1):
        for url in urls:
            try:
                time.sleep(0.45)
                r = get_session(UA).get(url, timeout=(20, 60), headers={"User-Agent": UA, "Accept": "text/html"})
                last = r
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(min(20, 2 ** attempt))
                    continue
                if r.status_code != 200 or not r.content:
                    continue
                raw = r.content.decode("latin-1", "replace")
                if "TSPD" in raw or "bobcmn" in raw:
                    log.info("TSPD on %s (%s B)", url, len(r.content))
                    continue
                return r, raw, url
            except Exception as exc:
                last = exc
                time.sleep(min(8, 1.2 * attempt))
    return last, "", ""


def year_entries(dtype: str, year: int) -> list[dict]:
    r, raw, used = get_html(f"/eli/{dtype}/{year}")
    if not raw:
        return []
    entries = []
    for m in re.finditer(rf"eli/{dtype}/{year}/(\d{{2}})/(\d{{2}})/([0-9A-Za-z]+)/justel", raw, re.I):
        mm, dd, numac = m.group(1), m.group(2), m.group(3)
        eli = f"https://www.ejustice.just.fgov.be/eli/{dtype}/{year}/{mm}/{dd}/{numac}/justel"
        entries.append({"dtype": dtype, "year": year, "mm": mm, "dd": dd, "numac": numac, "eli": eli})
    seen, out = set(), []
    for e in entries:
        if e["numac"] in seen:
            continue
        seen.add(e["numac"]); out.append(e)
    log.info("%s %s n=%s via %s", dtype, year, len(out), used)
    return out


def fetch_one(e: dict, done: set[str]) -> str:
    ident = f"{e['dtype']}-{e['year']}-{e['numac']}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    url = e["eli"]
    r, raw, used = get_html(url)
    if not raw or len(raw) < 400:
        log_failure(CC, {"identifier": ident, "source_url": url, "status": "failed", "reason": "empty_or_tspd"})
        return "fail"
    # cgi article.pl often embeds the Texte block even when ELI is a shell
    if 'id="text"' not in raw and "list-title-3" not in raw:
        cn = f"{e['year']}{e['mm']}{e['dd']}"
        alt = f"/cgi_loi/article.pl?language=fr&lg_txt=f&cn_search={cn}01&caller=eli&view_numac={cn}01fr"
        r2, raw2, used2 = get_html(alt)
        if raw2 and len(raw2) > len(raw):
            raw, used = raw2, used2
    text = html_to_text(raw)
    if not text or len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": used or url, "status": "failed", "reason": "empty_text"})
        return "fail"
    title = ident
    m = re.search(r'class="list-item--title">\s*([^<]{8,400})', raw, re.I)
    if m:
        title = re.sub(r"<[^>]+>", " ", m.group(1))
        title = re.sub(r"\s+", " ", title).strip()
    else:
        m = re.search(r"<title>([^<]+)</title>", raw, re.I)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
    rec = base_record(
        cc=CC, country=COUNTRY, language="fr", ident=ident, title=title, text=text,
        source_url=used or url, source_type=SOURCE_TYPE, license_text=LICENSE, collector="be-justel-eli",
        eli=url, date=f"{e['year']}-{e['mm']}-{e['dd']}",
        official_identifier=e["numac"], document_type=e["dtype"],
        law_status="current", is_current=True,
        extra_meta={"discovery": {"method": "eli_year_list", "dtype": e["dtype"]}},
    )
    rec["languages"] = ["fr", "nl", "de"]
    write_instrument(CC, rec)
    return "ok"


def main():
    setup(); t0 = utcnow()
    done = existing_ids(CC)
    catalog = []
    seen = set()
    catp = ROOT / CC / "raw" / "catalog.jsonl"
    if catp.exists() and catp.stat().st_size > 200:
        for line in catp.open(encoding="utf-8"):
            try:
                e = json.loads(line)
            except Exception:
                continue
            key = (e.get("dtype"), e.get("numac"))
            if e.get("eli") and key not in seen:
                seen.add(key); catalog.append(e)
        log.info("resume catalog %s", len(catalog))
    if not catalog:
        for dtype in TYPES:
            if dtype in ("constitution", "grondwet"):
                years = [1831, 1994, 2001, 2014, 2021]
            else:
                years = list(range(1990, 2027))
                if dtype in ("loi", "wet"):
                    years = list(range(1831, 1990, 5)) + years
            for year in years:
                ents = year_entries(dtype, year)
                for e in ents:
                    key = (e["dtype"], e["numac"])
                    if key in seen:
                        continue
                    seen.add(key); catalog.append(e); append_catalog(CC, e)
    ok = skip = fail = 0
    notes = (
        "Official ELI year listings on ejustice.just.fgov.be (loi/wet/decret/ordonnance/arrete/constitution). "
        "HTTPS sometimes RemoteDisconnects or returns F5 TSPD; collector falls back to HTTP and skips TSPD shells. "
        "Act HTML from /eli/.../justel and cgi_loi/article.pl Texte block. "
        "data.gov.be FPS Justice OGD publishes company-annex PDFs only, not consolidations."
    )
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(fetch_one, e, done) for e in catalog]
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
                log.info("progress %s/%s ok=%s fail=%s", n, len(catalog), ok, fail)
                write_summary(CC, country=COUNTRY, source="Justel / Moniteur belge ELI",
                              source_urls=["https://www.ejustice.just.fgov.be/eli/",
                                           "https://www.ejustice.just.fgov.be/cgi_loi/article.pl"],
                              license_text=LICENSE, discovered=len(catalog), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes=notes, last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="Justel / Moniteur belge official ELI",
                  source_urls=["https://www.ejustice.just.fgov.be/eli/",
                               "https://www.ejustice.just.fgov.be/cgi_loi/article.pl",
                               "https://data.gov.be/en/organisations/foed-justiz"],
                  license_text=LICENSE, discovered=len(catalog), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if catalog and fail == 0 else "catalog-backed incomplete",
                  notes=notes, last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s skip=%s fail=%s", len(catalog), ok, skip, fail)


if __name__ == "__main__":
    import json
    globals()["json"] = json
    main()
