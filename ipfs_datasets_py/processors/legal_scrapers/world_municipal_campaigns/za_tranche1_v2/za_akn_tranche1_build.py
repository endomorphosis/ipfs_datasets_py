"""South Africa AKN tranche 1 (v2, clean restart) — Open By-laws ingest.

Written fresh from the verified pilot builder
(hidden_files/za_pilot/za_pilot_build.py); no code or output from the
failed za_tranche1/ worker is used.

Scope: ALL 576 AKN works for the 11 AKN municipalities on
openbylaws.org.za (Laws.Africa / AfricanLII), enumerated from the
robots-referenced sitemap (cross-checked live against the reviewed
za_recon/akn_inventory.jsonl). Per-municipality output parquets contain
each municipality's COMPLETE harvestable AKN set in the world_municipal
19-column schema (MdbScheme), superseding the 5 pilot seed files in
place and adding the other 6 municipalities.

Robots: Allow:/, Crawl-delay 5, Disallow /api/, /search/,
/akn/*/provision/ — only sitemap + /akn/ document pages are fetched,
at 6 s pacing. The token-gated Laws.Africa Content API is NOT used.

Content gates are fail-closed: a work whose public page carries no AKN
HTML (PDF-only viewer-stub pages: "Loading PDF...", no akn-* markup)
or no extractable section-level units yields zero rows and is recorded
in excluded.jsonl with a reason — never forced. Afrikaans-only
expressions (afr@) are ingested as Afrikaans; the expression language
of every work is recorded in run_manifest.json.

Checkpointing: every fetched page is cached (gzip) under cache/ and
every processed work is appended to progress.jsonl; a municipality's
parquet is written as soon as all its works are processed. Re-running
resumes from cache + checkpoint without re-fetching.
"""
import gzip
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from bs4 import BeautifulSoup

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows, strip_tags  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402
from world_municipal.jurisdiction import get_scheme  # noqa: E402

BASE_DIR = Path.home() / "workspace/goals/world-municipal-law-coverage/hidden_files"
OUT = BASE_DIR / "za_tranche1_v2"
CACHE = OUT / "cache"
OUTD = OUT / "out"
for d in (CACHE, OUTD):
    d.mkdir(parents=True, exist_ok=True)
INVENTORY = BASE_DIR / "za_recon" / "akn_inventory.jsonl"
PILOT_MANIFEST = BASE_DIR / "za_pilot" / "run_manifest.json"

BASE = "https://openbylaws.org.za"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) world-municipal-law-tranche1/0.2"}
DELAY = 6.0
RETRIEVED = "2026-10-12"
ZA = get_scheme("ZA")

PLACES = {
    "za-cpt":   ("CPT",   "City of Cape Town"),
    "za-jhb":   ("JHB",   "City of Johannesburg"),
    "za-eth":   ("ETH",   "eThekwini"),
    "za-wc013": ("WC013", "Bergrivier"),
    "za-wc033": ("WC033", "Cape Agulhas"),
    "za-wc012": ("WC012", "Cederberg"),
    "za-wc023": ("WC023", "Drakenstein"),
    "za-wc041": ("WC041", "Kannaland"),
    "za-wc011": ("WC011", "Matzikama"),
    "za-wc015": ("WC015", "Swartland"),
    "za-ec443": ("EC443", "Winnie Madikizela-Mandela"),
}
# deterministic municipality order (metros first, then locals by code)
MDB_ORDER = ["CPT", "ETH", "JHB", "EC443", "WC011", "WC012", "WC013",
             "WC015", "WC023", "WC033", "WC041"]


class PoliteSession:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.last_start = 0.0
        self.n_requests = 0

    def get(self, url, timeout=120):
        last_exc = None
        for attempt in range(4):
            wait = DELAY - (time.monotonic() - self.last_start)
            if self.last_start and wait > 0:
                time.sleep(wait)
            if attempt:
                time.sleep(10 * attempt)
            self.last_start = time.monotonic()
            try:
                r = self.s.get(url, timeout=timeout)
                self.n_requests += 1
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r
            except Exception as exc:  # noqa: BLE001
                self.n_requests += 1
                last_exc = exc
        raise last_exc


# ---------------------------------------------------------------- units
UNIT_CLASSES = {"akn-section", "akn-preamble", "akn-schedule", "akn-preface"}


def has_unit_ancestor(el):
    for parent in el.parents:
        if parent is None or not getattr(parent, "get", None):
            continue
        if UNIT_CLASSES.intersection(parent.get("class") or []):
            return True
    return False


def extract_units(soup):
    """Pilot logic, unchanged: top-level section-level AKN units."""
    body = (soup.find("div", class_="content-and-enrichments__inner")
            or soup.find(id="document-content") or soup)
    units = []
    for el in body.find_all(True):
        classes = set(el.get("class") or [])
        if not classes.intersection(UNIT_CLASSES):
            continue
        if has_unit_ancestor(el):
            continue
        units.append(el)
    if not units:
        for el in body.find_all(True):
            classes = set(el.get("class") or [])
            if classes.intersection({"akn-part", "akn-chapter", "akn-body"}):
                if not el.find(class_=lambda c: c and "akn-section" in c):
                    units.append(el)
                    break
    out = []
    for el in units:
        uid = el.get("id") or "body"
        head = el.find(["h1", "h2", "h3", "h4"])
        label = re.sub(r"\s+", " ", head.get_text(" ", strip=True)) if head else uid
        out.append((uid, label, str(el)))
    return out


def has_akn_markup(soup):
    for el in soup.find_all(True):
        for cl in (el.get("class") or []):
            if cl.startswith("akn-"):
                return True
    return False


# ---------------------------------------------------------------- cache
def cache_path(work):
    safe = work["sitemap_loc"].strip("/").replace("/", "__")
    return CACHE / work["mdb"] / (safe + ".html.gz")


def load_cached(work):
    p = cache_path(work)
    if p.exists():
        return gzip.open(p, "rt", encoding="utf-8", errors="replace").read()
    return None


def save_cached(work, text):
    p = cache_path(work)
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------- main
def enumerate_works(sess):
    inv = [json.loads(l) for l in open(INVENTORY)]
    inv_by_loc = {w["sitemap_loc"]: w for w in inv}
    # live sitemap cross-check (robots-referenced route only)
    r = sess.get(f"{BASE}/sitemaps/legislation.xml")
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(r.text)
    live_locs = []
    for loc in root.findall(".//sm:loc", ns):
        t = loc.text or ""
        m = re.search(r"(/akn/za-[a-z0-9]+/.*)", t)
        if m:
            live_locs.append(m.group(1))
    works = []
    if set(live_locs) == set(inv_by_loc):
        print(f"sitemap cross-check OK: live == inventory == {len(live_locs)} works")
        works = inv
    else:
        print(f"WARNING sitemap differs: live {len(live_locs)} vs inventory "
              f"{len(inv_by_loc)}; using LIVE set")
        for loc_path in live_locs:
            if loc_path in inv_by_loc:
                works.append(inv_by_loc[loc_path])
                continue
            m = re.match(r"(/akn/(za-[a-z0-9]+)/act/([^/]+)/(\d{4})/(.+))/"
                         r"(eng|afr)@(\d{4}-\d{2}-\d{2})$", loc_path)
            if not m:
                print("unparsed live loc:", loc_path)
                continue
            wuri, place, subtype, year, slug, lang, date = m.groups()
            works.append({"place": place, "mdb": PLACES[place][0],
                          "work_uri": wuri, "subtype": subtype, "year": year,
                          "slug": slug.split("/")[0], "title": "",
                          "title_source": "slug", "expression_lang": lang,
                          "expression_date": date, "sitemap_loc": loc_path})
    order = {code: i for i, code in enumerate(MDB_ORDER)}
    works.sort(key=lambda w: (order.get(w["mdb"], 99), w["sitemap_loc"]))
    return works


def process_work(sess, work, done):
    """Returns (rows, doc_info). Rows may be [] for excluded works."""
    code, jname = PLACES[work["place"]]
    code = ZA.normalize(code)
    key = work["sitemap_loc"]
    if key in done:
        return None, done[key]
    html = load_cached(work)
    if html is None:
        r = sess.get(BASE + work["sitemap_loc"])
        html = r.text
        save_cached(work, html)
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1", class_="doc-title") or soup.find("h1")
    title = (re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
             if h1 else (work.get("title") or work["work_uri"]))
    units = extract_units(soup)
    rows = []
    parts = work["work_uri"].split("/")
    year = parts[5] if len(parts) > 5 else (work.get("year") or "")
    slug = "-".join(parts[6:]) if len(parts) > 6 else (work.get("slug") or "")
    expr_url = BASE + work["sitemap_loc"]
    work_url = BASE + work["work_uri"]
    for uid, label, body_html in units:
        text = strip_tags(body_html).strip()
        if not text:
            continue
        rows.append(make_row(
            jurisdiction_id=code, jurisdiction_name=jname, country="ZA",
            doc_id=f"{year}-{slug}-{uid}".replace("_", "-"),
            regeling_id=work["work_uri"], regeling_work_id=work["work_uri"],
            title=title,
            structural_path=f"{jname} > {title} > {label}",
            node_label=label, body_html=body_html,
            source_url=expr_url, xml_url=work_url,
            date_effective=work["expression_date"], retrieved=RETRIEVED,
        ))
    if rows:
        info = {"status": "ingested", "title": title, "work": work["work_uri"],
                "expression": expr_url, "lang": work["expression_lang"],
                "subtype": work["subtype"], "date": work["expression_date"],
                "rows": len(rows)}
    else:
        if "Loading PDF" in html or not has_akn_markup(soup):
            reason = ("pdf_only_no_akn_html: public page is a PDF viewer stub "
                      "with no AKN HTML content")
        else:
            reason = "no_extractable_units: AKN page yielded no section-level units"
        info = {"status": "excluded", "title": title, "work": work["work_uri"],
                "expression": expr_url, "lang": work["expression_lang"],
                "subtype": work["subtype"], "date": work["expression_date"],
                "rows": 0, "reason": reason}
    return rows, info


def main():
    sess = PoliteSession()
    works = enumerate_works(sess)
    print(f"total works: {len(works)}")

    # checkpoint state
    done = {}
    prog_path = OUT / "progress.jsonl"
    if prog_path.exists():
        for line in open(prog_path):
            try:
                rec = json.loads(line)
                done[rec["key"]] = rec["info"]
            except Exception:  # noqa: BLE001
                pass
    print(f"checkpoint: {len(done)} works already processed")
    prog = open(prog_path, "a")

    pilot_docs = {}
    if PILOT_MANIFEST.exists():
        pm = json.load(open(PILOT_MANIFEST))
        for code, v in pm["municipalities"].items():
            for d in v.get("docs", []):
                if "work" in d:
                    pilot_docs[d["work"]] = d["rows"]

    manifest = {"retrieved": RETRIEVED, "works_total": len(works),
                "municipalities": {}}
    mf_path = OUT / "run_manifest.json"
    if mf_path.exists():
        manifest = json.load(open(mf_path))

    by_mdb = {}
    for w in works:
        by_mdb.setdefault(w["mdb"], []).append(w)

    for code in MDB_ORDER:
        mworks = by_mdb.get(code, [])
        if not mworks:
            continue
        jname = PLACES[mworks[0]["place"]][1]
        rows, docs, excluded = [], [], []
        complete = True
        for i, work in enumerate(mworks):
            key = work["sitemap_loc"]
            try:
                wrows, info = process_work(sess, work, done)
            except Exception as exc:  # noqa: BLE001
                print(f"[{code} {i+1}/{len(mworks)}] FETCH-ERROR {key}: "
                      f"{str(exc)[:160]}", flush=True)
                complete = False
                continue
            if key not in done:
                done[key] = info
                prog.write(json.dumps({"key": key, "info": info}) + "\n")
                prog.flush()
            if info["status"] == "ingested":
                if wrows is None:
                    # rows were built in a previous run; rebuild from cache
                    wrows, _ = process_work(sess, work, {})
                rows.extend(wrows)
                docs.append(info)
            else:
                excluded.append(info)
            if (i + 1) % 10 == 0 or i + 1 == len(mworks):
                print(f"[{code}] {i+1}/{len(mworks)} ingested_docs={len(docs)} "
                      f"excluded={len(excluded)} rows={len(rows)} "
                      f"req={sess.n_requests}", flush=True)
        if not complete:
            print(f"{code}: INCOMPLETE (fetch errors remain) — parquet NOT written")
            manifest["municipalities"][code] = {
                "name": jname, "complete": False, "works": len(mworks),
                "docs_ingested": len(docs), "excluded": excluded}
            json.dump(manifest, open(mf_path, "w"), indent=2, ensure_ascii=False)
            continue
        rows = finalize_rows(rows)
        table = rows_to_table(rows)
        errors = validate_table(table, jurisdiction_id=code,
                                jurisdiction_name=jname, country="ZA")
        if errors:
            print(f"{code}: VALIDATION FAILED {errors}")
            manifest["municipalities"][code] = {
                "name": jname, "complete": True, "valid": False,
                "errors": errors, "works": len(mworks),
                "docs_ingested": len(docs), "excluded": excluded}
            json.dump(manifest, open(mf_path, "w"), indent=2, ensure_ascii=False)
            continue
        write_html_parquet(OUTD / f"{code}_html.parquet", table)
        reread = read_html_parquet(OUTD / f"{code}_html.parquet")
        report = validation_report(reread, jurisdiction_id=code,
                                   jurisdiction_name=jname, country="ZA")
        write_validation_report(OUTD / f"{code}_validation.json", report)
        assert report["valid"], report
        # pilot continuity check
        pilot_cmp = {}
        for d in docs:
            if d["work"] in pilot_docs:
                pilot_cmp[d["work"]] = {"pilot_rows": pilot_docs[d["work"]],
                                        "tranche_rows": d["rows"],
                                        "match": pilot_docs[d["work"]] == d["rows"]}
        manifest["municipalities"][code] = {
            "name": jname, "place": mworks[0]["place"], "complete": True,
            "valid": True, "works": len(mworks),
            "docs_ingested": len(docs), "docs_excluded": len(excluded),
            "rows": table.num_rows, "docs": docs, "excluded": excluded,
            "pilot_comparison": pilot_cmp,
            "requests_so_far": sess.n_requests}
        json.dump(manifest, open(mf_path, "w"), indent=2, ensure_ascii=False)
        print(f"{code} {jname}: works={len(mworks)} ingested={len(docs)} "
              f"excluded={len(excluded)} rows={table.num_rows} OK", flush=True)

    manifest["requests_total"] = sess.n_requests
    json.dump(manifest, open(mf_path, "w"), indent=2, ensure_ascii=False)
    tot_rows = sum(v.get("rows", 0) for v in manifest["municipalities"].values())
    tot_docs = sum(v.get("docs_ingested", 0) for v in manifest["municipalities"].values())
    tot_excl = sum(v.get("docs_excluded", 0) for v in manifest["municipalities"].values())
    print(f"DONE works={len(works)} docs_ingested={tot_docs} excluded={tot_excl} "
          f"rows={tot_rows} requests={sess.n_requests}")


if __name__ == "__main__":
    main()
