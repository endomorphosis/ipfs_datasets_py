#!/usr/bin/env python3
"""Croatia: Narodne novine official ELI API + gazette HTML (no /clanci index)."""
from __future__ import annotations
import json, logging, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *

CC, COUNTRY, SOURCE_TYPE = "hr", "Croatia", "narodne_novine"
LICENSE = (
    "Narodne novine official gazette (nn.hr). Metadata via official NN API "
    "(https://narodne-novine.nn.hr/nn_api.aspx); texts from official ELI HTML. "
    "Reuse per NN data_access terms; max 3 queries/s."
)
UA = DEFAULT_UA + " source=https://narodne-novine.nn.hr/"
BASE = "https://narodne-novine.nn.hr"
log = logging.getLogger("hr")


def setup():
    ensure_dirs(CC)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / CC / "logs" / "collector.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])


def api_get(path: str):
    r = http_get(BASE + path, ua=UA, sleep=0.4, headers={"Accept": "application/json"})
    return r


def api_post(path: str, payload: dict):
    last = None
    for attempt in range(1, 5):
        try:
            time.sleep(0.4)
            r = get_session(UA).post(BASE + path, json=payload, timeout=(20, 60),
                                     headers={"Accept": "application/json", "Content-Type": "application/json",
                                              "User-Agent": UA})
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(min(20, 2 ** attempt)); last = r; continue
            return r
        except Exception as exc:
            last = exc
            time.sleep(min(15, 1.5 * attempt))
    if isinstance(last, Exception):
        raise last
    return last


def discover() -> list[dict]:
    catp = ROOT / CC / "raw" / "catalog.jsonl"
    items, seen = [], set()
    if catp.exists() and catp.stat().st_size > 200:
        for line in catp.open(encoding="utf-8"):
            try:
                row = json.loads(line)
            except Exception:
                continue
            key = (row.get("year"), row.get("number"), str(row.get("act_num")))
            if key not in seen and row.get("act_num") is not None:
                seen.add(key); items.append(row)
        if items:
            log.info("resume catalog %s", len(items))
            return items
    r = api_get("/api/index")
    if r.status_code != 200:
        log.info("index HTTP %s %s", r.status_code, r.text[:200])
        return items
    try:
        years = r.json()
    except Exception:
        return items
    log.info("years %s", years)
    for year in years:
        er = api_post("/api/editions", {"part": "SL", "year": int(year)})
        if er.status_code != 200:
            log.info("editions %s HTTP %s", year, er.status_code)
            continue
        try:
            editions = er.json() or []
        except Exception:
            continue
        log.info("year %s editions=%s", year, len(editions))
        for num in editions:
            ar = api_post("/api/acts", {"part": "SL", "year": int(year), "number": int(num)})
            if ar.status_code != 200:
                continue
            try:
                acts = ar.json() or []
            except Exception:
                continue
            for act in acts:
                act_num = str(act)
                key = (int(year), int(num), act_num)
                if key in seen:
                    continue
                seen.add(key)
                rec = {
                    "part": "SL",
                    "year": int(year),
                    "number": int(num),
                    "act_num": act_num,
                    "eli": f"{BASE}/eli/sluzbeni/{year}/{num}/{act_num}",
                }
                items.append(rec)
                append_catalog(CC, rec)
            if int(num) % 20 == 0:
                log.info("year %s ed %s catalog=%s", year, num, len(items))
    return items


def fetch_one(row: dict, done: set[str]) -> str:
    year, num, act = row["year"], row["number"], row["act_num"]
    ident = f"sluzbeni-{year}-{num}-{act}"
    rid = slug_id(CC, ident)
    if rid in done:
        return "skip"
    eli = row.get("eli") or f"{BASE}/eli/sluzbeni/{year}/{num}/{act}"
    html_url = eli
    r = http_get(html_url, ua=UA, sleep=0.45, timeout=(15, 50))
    if r.status_code != 200 or not r.content:
        log_failure(CC, {"identifier": ident, "source_url": eli, "status": "failed", "reason": f"http_{r.status_code}"})
        return "fail"
    text = html_to_text(r.text)
    if not text or len(text) < 80:
        log_failure(CC, {"identifier": ident, "source_url": eli, "status": "failed", "reason": "empty_or_chrome"})
        return "fail"
    title = ident
    m = re.search(r"<title>([^<]+)</title>", r.text, re.I)
    if m:
        title = re.sub(r"\s+", " ", m.group(1)).strip()
    rec = base_record(
        cc=CC, country=COUNTRY, language="hr", ident=ident, title=title, text=text,
        source_url=eli, source_type=SOURCE_TYPE, license_text=LICENSE, collector="hr-nn-eli-api",
        eli=eli, date=None, official_identifier=f"NN {num}/{year} art.{act}",
        document_type="statute", law_status="unknown", is_current=None,
        extra_meta={"discovery": {"method": "nn_api", "year": year, "number": num, "act_num": act}},
    )
    write_instrument(CC, rec)
    return "ok"


def main():
    setup(); t0 = utcnow()
    items = discover()
    done = existing_ids(CC)
    ok = skip = fail = 0
    notes = (
        "Official NN REST API (index/editions/acts) plus ELI HTML. "
        "Old /clanci/sluzbeni/{year}/index.html 404s; ELI paths work. "
        "Polite 0.4s interval per NN data_access (max 3 qps)."
    )
    if not items:
        write_summary(CC, country=COUNTRY, source="Narodne novine official API",
                      source_urls=[BASE+"/", BASE+"/nn_api.aspx", BASE+"/data_access.aspx"],
                      license_text=LICENSE, discovered=0, fetched=0, skipped=0, failed=0,
                      coverage="catalog-backed incomplete", notes="NN API returned no catalog. "+notes,
                      last_run=utcnow())
        return
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(fetch_one, it, done) for it in items]
        n = 0
        for fut in as_completed(futs):
            n += 1
            try:
                st = fut.result()
            except Exception as exc:
                st = "fail"
                log_failure(CC, {"status": "failed", "reason": repr(exc)})
            ok += st == "ok"; skip += st == "skip"; fail += st == "fail"
            if n % 100 == 0:
                log.info("progress %s/%s ok=%s fail=%s", n, len(items), ok, fail)
                write_summary(CC, country=COUNTRY, source="Narodne novine official ELI API",
                              source_urls=[BASE+"/", BASE+"/nn_api.aspx", BASE+"/data_access.aspx"],
                              license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                              coverage="catalog-backed incomplete", notes=notes, last_run=utcnow())
    write_summary(CC, country=COUNTRY, source="Narodne novine official gazette ELI API",
                  source_urls=[BASE+"/", BASE+"/nn_api.aspx", BASE+"/data_access.aspx",
                               BASE+"/eli/sluzbeni/"],
                  license_text=LICENSE, discovered=len(items), fetched=ok, skipped=skip, failed=fail,
                  coverage="full" if items and fail == 0 else "catalog-backed incomplete",
                  notes=notes + " Catalog: SL (službeni) 2015–present via /api/index+editions+acts.",
                  last_run=utcnow(), extra=f"started {t0}")
    log.info("done disc=%s ok=%s skip=%s fail=%s", len(items), ok, skip, fail)


if __name__ == "__main__":
    main()
