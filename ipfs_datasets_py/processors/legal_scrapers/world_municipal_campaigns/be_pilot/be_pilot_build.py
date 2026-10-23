"""Belgium (Flanders) municipal-law pilot — LBLOD centrale vindplaats harvest.

Bounded pilot: 5 gemeenten x up to 4 reglement-type besluiten with
inline full text each. LOCAL ONLY — no uploads.

Source: LBLOD (Lokale Besluiten als Gelinkt Open Data) "Centrale
Vindplaats" SPARQL endpoint, https://centrale-vindplaats.lblod.info/sparql
— the Flemish central register of local-government decisions harvested
from the municipalities' Gelinkt Notuleren publication environments.
robots.txt on both the SPARQL host and the publication host:
"User-agent: * / Disallow:" (fully permissive). No crawl-delay declared;
this script self-imposes 3s between requests.

Attribution: besluit -> eli:passed_by -> bestuursorgaan
(tijdspecialisatie) -> generiek:isTijdspecialisatieVan -> bestuursorgaan
-> besluit:bestuurt -> bestuurseenheid (classification = Gemeente).

Normalization: world_municipal 19-column schema. Jurisdiction IDs are
Statbel NIS municipality codes (5 digits), verified against Statbel's
official Population_par_commune.xlsx ("Code INS" column, 2026 sheet).
NOTE: world_municipal/jurisdiction.py has NO BE scheme registered
(SCHEMES = NL/PT/ES/PL/KR/BR/EU/US) — this script mirrors the closest
registered pattern (INEMunicipioScheme: digit string, zero-padded) at
width 5 locally and flags the gap in the pilot report. The repo file is
NOT modified.
"""
import html as htmlmod
import json
import re
import sys
import time
from pathlib import Path

import requests

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows, strip_tags  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report, read_html_parquet  # noqa: E402

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "be_pilot"
OUT.mkdir(parents=True, exist_ok=True)

EP = "https://centrale-vindplaats.lblod.info/sparql"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) world-municipal-law-pilot/0.1",
      "Accept": "application/sparql-results+json"}
DELAY = 3.0            # self-imposed politeness (robots declares no delay)
SAMPLE = 4             # besluiten per gemeente
CANDIDATES = 14        # enumerated candidates per gemeente before filtering
RETRIEVED = "2026-10-12"
GEMEENTE_CLASS = "http://data.vlaanderen.be/id/concept/BestuurseenheidClassificatieCode/5ab0e9b8a3b2ca7c5e000001"

PFX = """PREFIX besluit: <http://data.vlaanderen.be/ns/besluit#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX eli: <http://data.europa.eu/eli/ontology#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX generiek: <https://data.vlaanderen.be/ns/generiek#>
"""

# Regulation document types from the live BesluitType concept scheme
# (labels fetched 2026-10-12 from the endpoint itself).
REG_TYPES = {
    "67378dd0-5413-474b-8996-d992ef81637a": "Reglementen en verordeningen",
    "ba5922c9-cfad-4b2e-b203-36479219ba56": "Retributiereglement",
    "e8afe7c5-9640-4db8-8f74-3f023bec3241": "Politiereglement",
    "256bd04a-b74b-4f2a-8f5d-14dda4765af9": "Tijdelijke politieverordening (op het wegverkeer)",
    "7d95fd2e-3cc9-4a4c-a58e-0fbc408c2f9b": "Aanvullend reglement op het wegverkeer (gewestwegen)",
    "4d8f678a-6fa4-4d5f-a2a1-80974e43bf34": "Aanvullend reglement op het wegverkeer (gemeentewegen)",
    "fb92601a-d189-4482-9922-ab0efc6bc935": "Gebruikersreglement",
    "a8486fa3-6375-494d-aa48-e34289b87d5b": "Huishoudelijk reglement",
    "e8aee49e-8762-4db2-acfe-2d5dd3c37619": "Reglement Onderwijs",
    "4673d472-8dbc-4cea-b3ab-f92df3807eb3": "Personeelsreglement",
    "fb21d14b-734b-48f4-bd4e-888163fd08e8": "Rechtspositieregeling (RPR)",
    "5ee63f84-2fa0-4758-8820-99dca2bdce7c": "Delegatiereglement",
    "25deb453-ae3e-4d40-8027-36cdb48ab738": "Deontologische Code",
    "4c22ef0a-f808-41dd-9c9f-2aff17fd851f": "Contantbelasting",
    "8597e056-b96d-4213-ad4c-37338f2aaf35": "Kohierbelasting",
    "b2d0734d-13d0-44b4-9af8-1722933c5288": "Aanvullende belasting of opcentiem",
    "d7060f97-c417-474c-abc6-ef006cb61f41": "Subsidie, premie, erkenning",
}
TYPE_BASE = "https://data.vlaanderen.be/id/concept/BesluitType/"

# name -> Statbel NIS code (verified vs Statbel Population_par_commune.xlsx, "Code INS")
GEMEENTEN = [
    dict(name="Kortenberg", nis="24055"),
    dict(name="Lanaken",    nis="73042"),
    dict(name="Essen",      nis="11016"),
    dict(name="Linkebeek",  nis="23100"),
    dict(name="Bierbeek",   nis="24011"),
]


def nis_normalize(code: str) -> str:
    """Closest registered pattern (INE/DICOFRE digit zfill), NIS width 5."""
    s = str(code).strip()
    if not s.isdigit():
        raise ValueError(f"not a NIS code: {code!r}")
    return s.zfill(5)


class SparqlClient:
    """SPARQL GET client with politeness delay + latency accounting."""

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.last_start = 0.0
        self.n_requests = 0
        self.fetch_seconds = 0.0

    def query(self, sparql: str):
        last_exc = None
        for attempt in range(4):
            wait = DELAY - (time.monotonic() - self.last_start)
            if self.last_start and wait > 0:
                time.sleep(wait)
            if attempt:
                time.sleep(5 * attempt)  # backoff on retry (endpoint latency is spiky)
            self.last_start = time.monotonic()
            t0 = time.monotonic()
            try:
                r = self.s.get(EP, params={"query": sparql,
                                           "format": "application/sparql-results+json"},
                               timeout=150)
            except requests.RequestException as e:
                last_exc = e
                self.n_requests += 1
                self.fetch_seconds += time.monotonic() - t0
                continue
            dt = time.monotonic() - t0
            self.n_requests += 1
            self.fetch_seconds += dt
            if r.status_code >= 500:
                last_exc = requests.HTTPError(f"HTTP {r.status_code}")
                continue
            r.raise_for_status()
            return r.json()["results"]["bindings"], dt
        raise last_exc


def bindings_map(bindings):
    return [{k: v["value"] for k, v in b.items()} for b in bindings]


def enumerate_candidates(client, gemeente_naam):
    values = " ".join(f"<{TYPE_BASE}{u}>" for u in REG_TYPES)
    sparql = PFX + f"""
SELECT DISTINCT ?b ?title ?datepub ?type WHERE {{
  VALUES ?type {{ {values} }}
  ?b a besluit:Besluit ; a ?type ; prov:value ?v ;
     eli:passed_by ?org ; eli:title ?title .
  OPTIONAL {{ ?b eli:date_publication ?datepub }}
  ?org generiek:isTijdspecialisatieVan ?orgF .
  ?orgF besluit:bestuurt ?e .
  ?e skos:prefLabel "{gemeente_naam}" ; besluit:classificatie <{GEMEENTE_CLASS}> .
}} ORDER BY DESC(?datepub) LIMIT {CANDIDATES}"""
    rows, dt = client.query(sparql)
    return bindings_map(rows), dt


def fetch_detail(client, besluit_uri):
    sparql = PFX + f"""
SELECT ?title ?desc ?datepub ?motivering ?derived ?value ?orgaanLabel WHERE {{
  <{besluit_uri}> eli:title ?title .
  OPTIONAL {{ <{besluit_uri}> eli:description ?desc }}
  OPTIONAL {{ <{besluit_uri}> eli:date_publication ?datepub }}
  OPTIONAL {{ <{besluit_uri}> besluit:motivering ?motivering }}
  OPTIONAL {{ <{besluit_uri}> prov:wasDerivedFrom ?derived }}
  OPTIONAL {{ <{besluit_uri}> prov:value ?value }}
  OPTIONAL {{
    <{besluit_uri}> eli:passed_by ?org .
    ?org besluit:classificatie ?cls . ?cls skos:prefLabel ?orgaanLabel .
  }}
}} LIMIT 1"""
    rows, dt = client.query(sparql)
    out = bindings_map(rows)
    return (out[0] if out else {}), dt


def fetch_articles(client, besluit_uri):
    sparql = PFX + f"""
SELECT ?number ?value WHERE {{
  <{besluit_uri}> eli:has_part ?a .
  ?a a besluit:Artikel ; prov:value ?value .
  OPTIONAL {{ ?a eli:number ?number }}
}}"""
    rows, dt = client.query(sparql)
    arts = bindings_map(rows)
    def key(a):
        try:
            return (0, int(a.get("number", "")), "")
        except ValueError:
            return (1, 0, a.get("number", ""))
    return sorted(arts, key=key), dt


HTMLISH = re.compile(r"<(p|div|br|ul|ol|li|table|h\d|span)\b", re.I)
ART_SPLIT = re.compile(r"(?=Artikel\s+\d+)", re.M)


def body_to_html(text: str) -> str:
    """Wrap a besluit/article body as schema html (mirrors pilot chunking)."""
    if HTMLISH.search(text):
        return f'<div class="chunk-content">{text}</div>'
    esc = htmlmod.escape(text.strip())
    paras = [p.strip() for p in re.split(r"\n\s*\n", esc) if p.strip()]
    if not paras:
        paras = [esc.replace("\n", "<br/>")]
    inner = "".join(f"<p>{p.replace(chr(10), '<br/>')}</p>" for p in paras)
    return f'<div class="chunk-content">{inner}</div>'


def besluit_rows(gemeente, detail, articles, besluit_uri, type_label):
    """Build schema rows for one besluit: article rows when the besluit is
    article-structured, else split the besluit-level text on Artikel heads."""
    nis = gemeente["nis"]
    name = gemeente["name"]
    title = (detail.get("title") or "").strip()
    datepub = (detail.get("datepub") or "")[:10]
    source = detail.get("derived", "")
    orgaan = detail.get("orgaanLabel", "")
    path_head = " > ".join(x for x in [name, orgaan, type_label, title] if x)
    rows = []

    def add(node_label, body, suffix):
        if not body or not body.strip():
            return
        html = body_to_html(body)
        rows.append(make_row(
            jurisdiction_id=nis, jurisdiction_name=name, country="BE",
            doc_id=f"{besluit_uri.rsplit('/', 1)[-1]}-{suffix}",
            regeling_id=besluit_uri, regeling_work_id=besluit_uri,
            title=title, structural_path=f"{path_head} > {node_label}" if node_label else path_head,
            node_label=node_label, html=html,
            source_url=source, date_effective=datepub, retrieved=RETRIEVED,
        ))

    if articles:
        for a in articles:
            num = (a.get("number") or "").strip()
            add(f"Artikel {num}" if num else "Artikel", a.get("value", ""),
                f"art-{num or 'x'}")
    else:
        value = detail.get("value", "")
        parts = [p for p in ART_SPLIT.split(value) if p.strip()]
        if len(parts) > 1:
            for p in parts:
                m = re.match(r"Artikel\s+(\d+)", p.strip())
                if m:
                    add(f"Artikel {m.group(1)}", p, f"art-{m.group(1)}")
                else:
                    add("Aanhef", p, "preamble")
        elif parts:
            add("", parts[0], "full")
    return rows


def main():
    client = SparqlClient()
    manifest = {"endpoint": EP, "retrieved": RETRIEVED, "gemeenten": []}
    for g in GEMEENTEN:
        g = dict(g, nis=nis_normalize(g["nis"]))
        entry = {"name": g["name"], "nis": g["nis"], "candidates": 0,
                 "harvested": [], "rows": 0, "requests_before": client.n_requests}
        cands, _ = enumerate_candidates(client, g["name"])
        # A besluit can carry two regulation type concepts -> dedupe by URI
        # (first type wins) or the same besluit would be harvested twice.
        seen_uris, uniq_cands = set(), []
        for cand in cands:
            if cand["b"] not in seen_uris:
                seen_uris.add(cand["b"])
                uniq_cands.append(cand)
        entry["candidates_raw"] = len(cands)
        entry["candidates"] = len(uniq_cands)
        cands = uniq_cands
        all_rows = []
        for cand in cands:
            if len(entry["harvested"]) >= SAMPLE:
                break
            uri = cand["b"]
            detail, _ = fetch_detail(client, uri)
            articles, _ = fetch_articles(client, uri)
            type_label = REG_TYPES.get(cand["type"].rsplit("/", 1)[-1], "")
            rows = besluit_rows(g, {**detail, "value": cand.get("v", "")} if False else detail,
                                articles, uri, type_label)
            # detail query re-fetches prov:value; use it when articles absent
            if not rows:
                continue
            all_rows.extend(rows)
            entry["harvested"].append({
                "besluit": uri, "title": detail.get("title", cand.get("title", "")),
                "type": type_label, "date_publication": detail.get("datepub", ""),
                "source_url": detail.get("derived", ""),
                "articles": len(articles), "rows": len(rows)})
        if not all_rows:
            entry["error"] = "no usable reglement besluiten with text"
            manifest["gemeenten"].append(entry)
            print(f"{g['name']}: NO ROWS")
            continue
        all_rows = finalize_rows(all_rows)
        table = rows_to_table(all_rows)
        errors = validate_table(table, jurisdiction_id=g["nis"],
                                jurisdiction_name=g["name"], country="BE")
        if errors:
            entry["error"] = "validation failed: " + "; ".join(errors)
            manifest["gemeenten"].append(entry)
            print(f"{g['name']}: VALIDATION FAILED {errors}")
            continue
        n = write_html_parquet(OUT / f"{g['nis']}_html.parquet", table)
        write_validation_report(OUT / f"{g['nis']}_validation.json",
                                validation_report(table, jurisdiction_id=g["nis"],
                                                  jurisdiction_name=g["name"], country="BE"))
        entry["rows"] = n
        entry["requests"] = client.n_requests - entry.pop("requests_before")
        manifest["gemeenten"].append(entry)
        print(f"{g['name']} ({g['nis']}): {len(entry['harvested'])} besluiten -> {n} rows")
    manifest["total_requests"] = client.n_requests
    manifest["total_fetch_seconds"] = round(client.fetch_seconds, 1)
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"TOTAL: {client.n_requests} SPARQL requests, {client.fetch_seconds:.1f}s fetch")


if __name__ == "__main__":
    main()
