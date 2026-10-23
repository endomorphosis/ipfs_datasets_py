"""South Africa municipal-law pilot — OpenByLaws / Laws.Africa AKN ingest.

Adopt-first pilot: 5 municipalities x up to 4 by-laws, ingested from the
public Akoma Ntoso (AKN) HTML expressions on openbylaws.org.za — NOT
scraped from municipal sites and NOT via any API.

Route verification (live, 2026-10-12):
- openbylaws.org.za is a PeachJam site by Laws.Africa / AfricanLII,
  part of LawLibrary.org.za. It carries by-laws for 11 municipalities
  (site navigation + robots.txt place list agree).
- robots.txt (User-agent: *): "Allow: /", Crawl-delay: 5, Disallow:
  /api/, /accounts/, /my/, /user/, /purchase/, /judgments/, /gazettes/,
  /search/, /akn/*/provision/*. This script honours all of it: it uses
  ONLY the sitemap referenced in robots.txt (/sitemaps/legislation.xml),
  the /legislation/<place>/ listing pages, and the /akn/<place>/...
  document pages; it self-imposes 6 s between requests (> crawl-delay).
  Content-Signal header in robots: ai-train=no, search=yes,
  ai-input=no — documented in the pilot report as a flagged ambiguity
  for scale / AI-training use; this pilot is a non-commercial open-law
  republication with attribution (see report).
- laws.africa/robots.txt: "User-agent: * / Allow: /" (fully permissive).
- Laws.Africa Content API (api.laws.africa) is a separate, token-gated,
  paid-tier service and its /api/ path is robots-disallowed on
  openbylaws.org.za — NOT used. Content license stated on
  laws.africa/api: CC-BY-NC-SA with attribution to Laws.Africa and
  contributors; SAFLII's OpenByLaws mirror notes there is no copyright
  in the original by-law content and the HTML form was CC BY 2.5 ZA.
  Attribution is carried into the dataset card.

Jurisdiction IDs: Municipal Demarcation Board (MDB) codes, registered
this pilot as world_municipal MdbScheme (ZA) in the repo working tree
(local only, no commit/push; suite 36 -> 37 tests, all pass). Registry
of all 257 municipalities (8 metro + 44 district + 205 local, post-2016
demarcation) transcribed from the Wikipedia "List of municipalities in
South Africa" tables (themselves sourced to the MDB / Stats SA) and
count-verified: 257 unique codes. AKN place = "za-" + lower(code).

Normalization: world_municipal 19-column schema. One row per AKN
section-level unit (akn-section / akn-preamble / akn-schedule /
akn-preface, top-level only — subsections ride inside their section).
"""
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

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "za_pilot"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "https://openbylaws.org.za"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) world-municipal-law-pilot/0.1"}
DELAY = 6.0            # robots Crawl-delay is 5; stay above it
SAMPLE = 4             # by-laws per municipality
RETRIEVED = "2026-10-12"
ZA = get_scheme("ZA")

# AKN place -> (MDB code, jurisdiction_name as used on OpenByLaws)
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
PILOT_PLACES = ["za-cpt", "za-jhb", "za-eth", "za-wc013", "za-wc023"]


class PoliteSession:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.last_start = 0.0
        self.n_requests = 0
        self.fetch_seconds = 0.0

    def get(self, url, timeout=90):
        wait = DELAY - (time.monotonic() - self.last_start)
        if self.last_start and wait > 0:
            time.sleep(wait)
        last_exc = None
        for attempt in range(3):
            if attempt:
                time.sleep(5 * attempt)
            self.last_start = time.monotonic()
            t0 = time.monotonic()
            try:
                r = self.s.get(url, timeout=timeout)
                self.fetch_seconds += time.monotonic() - t0
                self.n_requests += 1
                r.raise_for_status()
                return r
            except Exception as exc:  # noqa: BLE001
                self.fetch_seconds += time.monotonic() - t0
                self.n_requests += 1
                last_exc = exc
        raise last_exc


# ---------------------------------------------------------------- registry

def build_registry(sess):
    """257 municipalities from the Wikipedia list tables (MDB codes)."""
    r = sess.get("https://en.wikipedia.org/wiki/List_of_municipalities_in_South_Africa")
    soup = BeautifulSoup(r.text, "html.parser")
    entries = {}

    def add(code, name, province, category, district=""):
        code = ZA.normalize(code)
        name = re.sub(r"\s+", " ", name).strip()
        if code in entries:  # metros repeat in district/local tables
            if category == "A":
                entries[code]["category"] = "A"
            return
        entries[code] = {
            "jurisdiction_id": code, "name": name, "country": "ZA",
            "province": province, "category": category, "district": district,
            "akn_place": "", "akn_works": 0, "in_pilot": False,
        }

    tables = soup.find_all("table", class_="wikitable")
    # table 0 = metros, table 1 = districts (+metros), table 2 = locals (+metros)
    for ti, category in [(0, "A"), (1, "C"), (2, "B")]:
        if ti >= len(tables):
            continue
        for tr in tables[ti].find_all("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            name, code, province = cells[0], cells[1], cells[2]
            district = cells[3] if (ti == 2 and len(cells) > 3) else ""
            if not code or not ZA.validate(code):
                continue
            cat = "A" if ZA.normalize(code) in ZA._METROS else category
            add(code, name, province, cat, district)
    for place, (code, _short) in PLACES.items():
        if code in entries:
            entries[code]["akn_place"] = place
    assert len(entries) == 257, f"registry count {len(entries)} != 257"
    cats = {}
    for e in entries.values():
        cats[e["category"]] = cats.get(e["category"], 0) + 1
    assert cats == {"A": 8, "C": 44, "B": 205}, f"category split {cats}"
    return entries


def sitemap_counts(sess):
    """Works per AKN place from the robots-referenced sitemap.
    The sitemap's <loc> host is a placeholder (example.com); paths are real."""
    r = sess.get(f"{BASE}/sitemaps/legislation.xml")
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(r.text)
    counts, total = {}, 0
    for loc in root.findall(".//sm:loc", ns):
        m = re.search(r"/akn/(za-[a-z0-9]+)/", loc.text or "")
        if m:
            counts[m.group(1)] = counts.get(m.group(1), 0) + 1
            total += 1
    return counts, total


# ---------------------------------------------------------------- harvest

UNIT_CLASSES = {"akn-section", "akn-preamble", "akn-schedule", "akn-preface"}


def has_unit_ancestor(el):
    for parent in el.parents:
        if parent is None or not getattr(parent, "get", None):
            continue
        if UNIT_CLASSES.intersection(parent.get("class") or []):
            return True
    return False


def extract_units(soup):
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
    # parts/chapters with no section descendants are units in their own right
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


def parse_doc(sess, place, href):
    url = BASE + href
    r = sess.get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1", class_="doc-title") or soup.find("h1")
    title = re.sub(r"\s+", " ", h1.get_text(" ", strip=True)) if h1 else href
    m = re.search(r"eng@(\d{4}-\d{2}-\d{2})", href)
    expr_date = m.group(1) if m else ""
    work_href = href.split("/eng@")[0]
    work_uri = "/akn/" + href.split("/akn/", 1)[1].split("/eng@")[0]
    units = extract_units(soup)
    return title, expr_date, work_uri, BASE + work_href, url, units


def main():
    sess = PoliteSession()
    registry = build_registry(sess)
    (OUT / "registry_build_note.txt").write_text("registry ok: 257 (8A/44C/205B)\n")
    counts, total_works = sitemap_counts(sess)
    for place, n in counts.items():
        if place in PLACES:
            registry[PLACES[place][0]]["akn_works"] = n
    print(f"sitemap: {total_works} works, per-place {counts}")

    manifest = {"retrieved": RETRIEVED, "sitemap_works_total": total_works,
                "sitemap_per_place": counts, "municipalities": {}}
    for place in PILOT_PLACES:
        code, jname = PLACES[place]
        code = ZA.normalize(code)
        registry[code]["in_pilot"] = True
        r = sess.get(f"{BASE}/legislation/{place}/")
        soup = BeautifulSoup(r.text, "html.parser")
        hrefs, seen = [], set()
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if f"/akn/{place}/act/by-law/" in h and h not in seen:
                seen.add(h)
                hrefs.append(h)
        rows, docs = [], []
        for href in hrefs[:SAMPLE * 2]:
            if len(docs) >= SAMPLE:
                break
            try:
                title, expr_date, work_uri, work_url, expr_url, units = parse_doc(sess, place, href)
            except Exception as exc:  # noqa: BLE001
                docs.append({"href": href, "error": str(exc)[:200]})
                continue
            slug = work_uri.rstrip("/").rsplit("/", 1)[-1]
            year = work_uri.split("/")[5] if len(work_uri.split("/")) > 5 else ""
            n_before = len(rows)
            for uid, label, body_html in units:
                text = strip_tags(body_html).strip()
                if not text:
                    continue
                rows.append(make_row(
                    jurisdiction_id=code, jurisdiction_name=jname, country="ZA",
                    doc_id=f"{year}-{slug}-{uid}".replace("_", "-"),
                    regeling_id=work_uri, regeling_work_id=work_uri,
                    title=title,
                    structural_path=f"{jname} > {title} > {label}",
                    node_label=label, body_html=body_html,
                    source_url=expr_url, xml_url=work_url,
                    date_effective=expr_date, retrieved=RETRIEVED,
                ))
            if len(rows) > n_before:
                docs.append({"title": title, "work": work_uri, "expression": expr_url,
                             "date": expr_date, "rows": len(rows) - n_before})
        rows = finalize_rows(rows)
        table = rows_to_table(rows)
        errors = validate_table(table, jurisdiction_id=code,
                                jurisdiction_name=jname, country="ZA")
        if errors:
            manifest["municipalities"][code] = {"name": jname, "place": place,
                                                "valid": False, "errors": errors, "docs": docs}
            print(f"{code} {jname}: VALIDATION FAILED {errors}")
            continue
        write_html_parquet(OUT / f"{code}_html.parquet", table)
        reread = read_html_parquet(OUT / f"{code}_html.parquet")
        report = validation_report(reread, jurisdiction_id=code,
                                   jurisdiction_name=jname, country="ZA")
        write_validation_report(OUT / f"{code}_validation.json", report)
        assert report["valid"], report
        manifest["municipalities"][code] = {
            "name": jname, "place": place, "valid": True,
            "bylaws_listed": len(hrefs), "docs": docs,
            "rows": table.num_rows,
            "requests_so_far": sess.n_requests, "fetch_seconds": round(sess.fetch_seconds, 1),
        }
        print(f"{code} {jname}: {len(docs)} docs listed={len(hrefs)} rows={table.num_rows} OK")

    # full registry with AKN coverage joined
    reg_list = sorted(registry.values(), key=lambda e: e["jurisdiction_id"])
    (OUT / "jurisdictions.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in reg_list) + "\n")
    manifest["registry"] = {"total": len(reg_list),
                            "akn_places": sorted(PLACES),
                            "akn_municipalities": sum(1 for e in reg_list if e["akn_place"])}
    manifest["requests_total"] = sess.n_requests
    manifest["fetch_seconds_total"] = round(sess.fetch_seconds, 1)
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(manifest["registry"], indent=2))
    print(f"requests={sess.n_requests} fetch={sess.fetch_seconds:.0f}s")


if __name__ == "__main__":
    main()
