"""Harvest current municipalities for every country from Wikidata.

One worldwide query times out. Municipality types are country-specific
subclasses of Q15284, so each subclass is fetched on its own. Dissolved
items and statements with an end date are left out. The curated US GNIS
file and the Netherlands pilot file are not overwritten.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.legal_scrapers.regions.mapping import (
    COUNTRY_TO_REGION,
    region_for_country,
)
from ipfs_datasets_py.processors.legal_scrapers.municipal.seed_harvest import (
    _cell,
    _number,
    _qid,
    _write_jsonl,
    classify_urls,
    sparql,
)

MUNICIPALITY = "Q15284"
# Curated seeds already on disk. World harvest must not replace them.
PRESERVE_FILES = {
    "US": "americas/US.jsonl",
    "NL": "europe/NL.jsonl",
}
# Local governments that are not within two hops of municipality Q15284.
# Provinces, states, and regions are not included. Finalize dedupes by QID,
# so a second item with the same label does not create a second row.
GAP_CLASSES: tuple[tuple[str, str], ...] = (
    ("Q70208", "municipality of Switzerland"),
    ("Q1867183", "local government area of Australia"),
    ("Q941036", "territorial authority of New Zealand"),
    ("Q112684326", "municipality of India"),
    ("Q2179958", "district of Peru"),
    ("Q2460358", "municipality of Turkey"),
    ("Q123165444", "municipality of Turkey"),
    ("Q1639634", "local government area of Nigeria"),
    ("Q612229", "municipality of Estonia"),
    ("Q28122896", "rural municipality of Estonia"),
    ("Q2655841", "municipality of Georgia"),
    ("Q76514543", "municipality of Georgia"),
    ("Q3345345", "municipality of Latvia"),
    ("Q838549", "municipality of Montenegro"),
    ("Q646793", "municipality of North Macedonia"),
    ("Q917092", "municipality of Paraguay"),
    ("Q3710488", "district of Panama"),
    ("Q3074936", "local government in the Republic of Ireland"),
    ("Q953822", "canton of Costa Rica"),
    ("Q936955", "parish of Jamaica"),
    ("Q29045252", "city of South Korea"),
    ("Q17143371", "county of South Korea"),
    ("Q706447", "county of Taiwan"),
    ("Q2367508", "township of Taiwan"),
    ("Q2389082", "commune of Vietnam"),
    ("Q545769", "district of Ghana"),
    ("Q1500352", "local municipality of South Africa"),
    ("Q1002812", "metropolitan borough"),
    ("Q211690", "London borough"),
    ("Q4296769", "metropolitan district"),
    ("Q1187580", "non-metropolitan district"),
    ("Q1289426", "county of China"),
    ("Q1070990", "county-level city of China"),
    ("Q748149", "prefecture-level city of China"),
    ("Q18670606", "tehsil of Pakistan"),
    ("Q269218", "county of Kenya"),
    ("Q2409750", "district of Tanzania"),
    ("Q1994931", "district of Malaysia"),
    ("Q19833031", "emirate of the United Arab Emirates"),
    ("Q1022469", "regional council of Israel"),
    ("Q1230110", "district of Sri Lanka"),
    ("Q57368", "district of Botswana"),
    ("Q5283558", "district of Zimbabwe"),
    ("Q496825", "district of Afghanistan"),
    ("Q690840", "district of Ethiopia"),
    ("Q2631599", "district of Uzbekistan"),
    ("Q2643128", "district of Kazakhstan"),
    ("Q4414032", "rural district of Kazakhstan"),
    ("Q1518096", "district of Mongolia"),
    ("Q2043199", "district of Belarus"),
    ("Q15071808", "rural council of Belarus"),
    ("Q7130304", "town panchayat"),
)
# Wikidata class for a country's top division: state, province, region, governorate.
FIRST_LEVEL = "Q10864048"
# These are first-level divisions but are not direct subclasses of FIRST_LEVEL,
# so the subclass walk never fetched them.
EXTRA_ADM1: tuple[tuple[str, str], ...] = (
    ("Q12443800", "state of India"),
    ("Q467745", "union territory of India"),
    ("Q485258", "federative unit of Brazil"),
    ("Q5098", "province of Indonesia"),
)
_SKIP_CLASS = re.compile(
    r"\b(former|historical|ancient|theoretical|fictional|abandoned|abolished|defunct|proposed|medieval|ottoman|roman|vilayet|assr)\b",
    re.I,
)
_MUNICIPAL_CLASS = re.compile(
    r"municipality|municipal|commune|local government|parish|borough|panchayat|nagar",
    re.I,
)
_CATALOG_NOISE = re.compile(
    r"\b(bicycle|friendly|award|medal|apostolic|reichsgau|eyalet|sanjak|byzantine|zhili|viceroyalty|czechoslovak)\b",
    re.I,
)
_ADM1_CLASS = re.compile(
    r"state|province|governorate|oblast|region|canton|voivodeship|krai|emirate|"
    r"prefecture|department|county|republic|territory|autonomous community",
    re.I,
)


def parts_root() -> Path:
    return Path.home() / ".ipfs_datasets" / "municipal-seeds" / "parts"


def skip_class_label(label: str) -> bool:
    return bool(_SKIP_CLASS.search(label or ""))


def is_province_class(label: str) -> bool:
    """A first-level division, not a municipality that Wikidata also nests there."""
    if skip_class_label(label):
        return False
    if _MUNICIPAL_CLASS.search(label or ""):
        return False
    return bool(_ADM1_CLASS.search(label or ""))


_LEVEL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("parish", r"\bparish(?:es)?\b"),
    ("district", r"\bdistricts?\b"),
    ("municipality", r"\bmunicipalit(?:y|ies)\b"),
    ("state", r"\bstates?\b"),
    ("province", r"\bprovinces?\b"),
    ("territory", r"\bterritor(?:y|ies)\b"),
    ("governorate", r"\bgovernorates?\b"),
    ("oblast", r"\boblasts?\b"),
    ("region", r"\bregions?\b"),
    ("canton", r"\bcantons?\b"),
    ("voivodeship", r"\bvoivodeships?\b"),
    ("krai", r"\bkrais?\b"),
    ("emirate", r"\bemirates?\b"),
    ("prefecture", r"\bprefectures?\b"),
    ("department", r"\bdepartments?\b"),
    ("county", r"\bcount(?:y|ies)\b"),
    ("republic", r"\brepublics?\b"),
)


def level_from_label(label: str) -> str | None:
    """Return a known government level, or None when the label is ambiguous."""
    text = re.sub(r"\bunited states\b", "usa", (label or "").lower())
    if "federative unit" in text:
        return "state"
    for name, pattern in _LEVEL_PATTERNS:
        if re.search(pattern, text):
            return name
    return None


def admin_level_for_label(label: str) -> str:
    return level_from_label(label) or "adm1"


def province_classes() -> list[tuple[str, str]]:
    """Direct subclasses of a first-level administrative division."""
    query = """
SELECT ?class ?classLabel WHERE {
  ?class wdt:P279 wd:Q10864048 .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""
    found: dict[str, str] = {FIRST_LEVEL: "first-level administrative division"}
    found.update(dict(EXTRA_ADM1))
    for binding in sparql(query, attempts=3, timeout=120.0):
        qid = _qid(_cell(binding, "class"))
        label = _cell(binding, "classLabel") or qid
        if qid and is_province_class(label):
            found[qid] = label
    return sorted(found.items(), key=lambda item: item[1].lower())


def _subclass_query(root: str, depth: int) -> str:
    """One hop of subclasses. Depth 3 is a separate query so a timeout does not drop hop 1."""
    if depth == 1:
        path = "wdt:P279"
        shorter = ""
    elif depth == 2:
        path = "wdt:P279/wdt:P279"
        shorter = f"FILTER NOT EXISTS {{ ?class wdt:P279 wd:{root} }}"
    elif depth == 3:
        path = "wdt:P279/wdt:P279/wdt:P279"
        shorter = (
            f"FILTER NOT EXISTS {{ ?class wdt:P279 wd:{root} }}\n"
            f"  FILTER NOT EXISTS {{ ?class wdt:P279/wdt:P279 wd:{root} }}"
        )
    else:
        raise ValueError(f"subclass depth {depth} is not walked")
    return f"""
SELECT ?class ?classLabel WHERE {{
  ?class {path} wd:{root} .
  {shorter}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
"""


def assemble_catalog(
    entries: Sequence[Mapping[str, Any]],
    done: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """One row per class. A province label wins over a municipality label."""
    finished = set(done or ())
    extra = {qid for qid, _label in EXTRA_ADM1}
    by_qid: dict[str, dict[str, Any]] = {}
    for entry in entries:
        qid = str(entry.get("qid") or "")
        label = str(entry.get("label") or qid)
        if not qid or label == qid or skip_class_label(label) or _CATALOG_NOISE.search(label):
            continue
        level = level_from_label(label)
        if level in {"district", "parish", "municipality"}:
            role = level
            admin_level = level
        elif is_province_class(label) or qid in extra or qid == FIRST_LEVEL or entry.get("role") == "adm1":
            role = "adm1"
            admin_level = level or "adm1"
        else:
            role = "municipality"
            admin_level = "municipality"
        record = {
            "qid": qid,
            "label": label,
            "role": role,
            "admin_level": admin_level,
            "depth": int(entry.get("depth") or 0),
            "root": str(entry.get("root") or ""),
            "done": qid in finished,
        }
        current = by_qid.get(qid)
        specific = {"district", "parish", "municipality"}
        if current is None:
            by_qid[qid] = record
            continue
        if current["role"] in specific and record["role"] == "adm1":
            if record["depth"] and not current["depth"]:
                current["depth"] = record["depth"]
                current["root"] = current["root"] or record["root"]
            continue
        if record["role"] in specific and current["role"] == "adm1":
            by_qid[qid] = record
            continue
        if record["role"] == "adm1" and current["role"] != "adm1":
            by_qid[qid] = record
            continue
        if record["depth"] and not current["depth"]:
            current["depth"] = record["depth"]
            current["root"] = current["root"] or record["root"]
    return sorted(by_qid.values(), key=lambda row: (row["role"], row["label"].lower(), row["qid"]))


def class_catalog(*, done: Iterable[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Walk municipality hops 1–3 and first-level divisions. Does not fetch places."""
    entries: list[dict[str, Any]] = [
        {"qid": MUNICIPALITY, "label": "municipality", "role": "municipality", "depth": 0, "root": MUNICIPALITY}
    ]
    errors: dict[str, str] = {}
    for depth in (1, 2, 3):
        try:
            bindings = sparql(_subclass_query(MUNICIPALITY, depth), attempts=3, timeout=180.0)
        except Exception as exc:
            errors[f"municipality-depth-{depth}"] = f"{type(exc).__name__}: {exc}"
            continue
        for binding in bindings:
            qid = _qid(_cell(binding, "class"))
            if not qid:
                continue
            entries.append(
                {
                    "qid": qid,
                    "label": _cell(binding, "classLabel") or qid,
                    "role": "municipality",
                    "depth": depth,
                    "root": MUNICIPALITY,
                }
            )
    entries.append(
        {
            "qid": FIRST_LEVEL,
            "label": "first-level administrative division",
            "role": "adm1",
            "depth": 0,
            "root": FIRST_LEVEL,
        }
    )
    for qid, label in EXTRA_ADM1:
        entries.append({"qid": qid, "label": label, "role": "adm1", "depth": 0, "root": FIRST_LEVEL})
    for qid, label in GAP_CLASSES:
        entries.append({"qid": qid, "label": label, "role": "municipality", "depth": 0, "root": "gap"})
    try:
        bindings = sparql(_subclass_query(FIRST_LEVEL, 1), attempts=3, timeout=180.0)
    except Exception as exc:
        errors["adm1-depth-1"] = f"{type(exc).__name__}: {exc}"
        bindings = []
    for binding in bindings:
        qid = _qid(_cell(binding, "class"))
        if not qid:
            continue
        entries.append(
            {
                "qid": qid,
                "label": _cell(binding, "classLabel") or qid,
                "role": "adm1",
                "depth": 1,
                "root": FIRST_LEVEL,
            }
        )
    return assemble_catalog(entries, done), errors


def write_class_catalog(dest: Path, *, parts: Path | None = None) -> dict[str, Any]:
    progress = _load_progress((parts or parts_root()) / "progress.json")
    records, errors = class_catalog(done=progress.get("done") or [])
    path = dest / "class_catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    new = [row for row in records if not row["done"]]
    summary = {
        "path": str(path),
        "classes": len(records),
        "new": len(new),
        "done": len(records) - len(new),
        "municipality": sum(1 for row in records if row["role"] == "municipality"),
        "adm1": sum(1 for row in records if row["role"] == "adm1"),
        "new_by_depth": {},
        "errors": errors,
    }
    depths: dict[str, int] = {}
    for row in new:
        key = str(row["depth"])
        depths[key] = depths.get(key, 0) + 1
    summary["new_by_depth"] = depths
    return summary


def municipality_classes() -> list[tuple[str, str]]:
    """Direct subclasses of municipality, plus one more hop, plus Q15284 itself."""
    query = """
SELECT ?class ?classLabel ?depth WHERE {
  {
    ?class wdt:P279 wd:Q15284 .
    BIND(1 AS ?depth)
  }
  UNION
  {
    ?class wdt:P279/wdt:P279 wd:Q15284 .
    FILTER NOT EXISTS { ?class wdt:P279 wd:Q15284 }
    BIND(2 AS ?depth)
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""
    found: dict[str, str] = {MUNICIPALITY: "municipality"}
    for binding in sparql(query, attempts=3, timeout=120.0):
        qid = _qid(_cell(binding, "class"))
        label = _cell(binding, "classLabel") or qid
        if qid and not skip_class_label(label):
            found[qid] = label
    return sorted(found.items(), key=lambda item: item[1].lower())


def _class_query(class_qid: str, *, prefix: str | None, end_qualifier: bool) -> str:
    prefix_filter = ""
    if prefix:
        prefix_filter = (
            "FILTER(STRSTARTS(STRAFTER(STR(?item), "
            f'"http://www.wikidata.org/entity/Q"), "{prefix}"))'
        )
    end_filter = ""
    if end_qualifier:
        end_filter = f"""
  FILTER NOT EXISTS {{
    ?item p:P31 ?stmt .
    ?stmt ps:P31 wd:{class_qid} ;
          pq:P582 ?ended .
  }}
"""
    return f"""
SELECT ?item ?iso ?en ?site ?gnis ?geonames ?iso3166 WHERE {{
  ?item wdt:P31 wd:{class_qid} .
  FILTER NOT EXISTS {{ ?item wdt:P576 ?dissolved }}
  {end_filter}
  {prefix_filter}
  OPTIONAL {{
    ?item wdt:P17 ?country .
    ?country wdt:P297 ?iso .
  }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item wdt:P856 ?site }}
  OPTIONAL {{ ?item wdt:P590 ?gnis }}
  OPTIONAL {{ ?item wdt:P1566 ?geonames }}
  OPTIONAL {{ ?item wdt:P300 ?iso3166 }}
}}
"""


def rows_from_bindings(
    bindings: Sequence[Mapping[str, Any]],
    class_qid: str,
    *,
    admin_level: str = "municipality",
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        qid = _qid(_cell(binding, "item"))
        if not qid:
            continue
        row = grouped.get(qid)
        if row is None:
            row = {
                "qid": qid,
                "isos": [],
                "name": "",
                "sites": [],
                "gnises": [],
                "geonames": [],
                "iso3166": [],
            }
            grouped[qid] = row
        iso = _cell(binding, "iso").upper()
        if iso and iso not in row["isos"]:
            row["isos"].append(iso)
        label = _cell(binding, "en")
        if label and not row["name"]:
            row["name"] = label
        site = _cell(binding, "site")
        if site and site not in row["sites"]:
            row["sites"].append(site)
        gnis = _cell(binding, "gnis")
        if gnis and gnis not in row["gnises"]:
            row["gnises"].append(gnis)
        geonames = _cell(binding, "geonames")
        if geonames and geonames not in row["geonames"]:
            row["geonames"].append(geonames)
        iso3166 = _cell(binding, "iso3166")
        if iso3166 and iso3166 not in row["iso3166"]:
            row["iso3166"].append(iso3166)
    rows: list[dict[str, Any]] = []
    for row in grouped.values():
        iso = _prefer_iso(row["isos"])
        url_class, publisher = classify_urls(row["sites"])
        try:
            region = region_for_country(iso) if iso else "unassigned"
        except KeyError:
            region = "unassigned"
        rows.append(
            {
                "qid": row["qid"],
                "gnis": row["gnises"][0] if row["gnises"] else "",
                "gnis_alt": row["gnises"][1:],
                "geonames_id": row["geonames"][0] if row["geonames"] else "",
                "name": row["name"],
                "wikidata_label": row["name"],
                "official_name": "",
                "country_code": iso,
                "region": region,
                "admin_level": admin_level,
                "wikidata_class": class_qid,
                "parent_qid": "",
                "iso_3166_2": row["iso3166"][0] if row["iso3166"] else "",
                "lat": _number(""),
                "lon": _number(""),
                "population": "",
                "source_urls": row["sites"],
                "url_class": url_class,
                "publisher": publisher,
                "status": "not_scraped",
                "lang": [],
            }
        )
    return rows


def _prefer_iso(isos: Sequence[str]) -> str:
    for iso in isos:
        if iso in COUNTRY_TO_REGION and iso != "EU":
            return iso
    for iso in isos:
        if iso and iso != "EU":
            return iso
    return ""


def fetch_class_rows(
    class_qid: str,
    *,
    delay: float = 0.3,
    admin_level: str = "municipality",
) -> list[dict[str, Any]]:
    """Fetch one municipality class, falling back to smaller slices if Wikidata times out."""
    attempts = (
        [(None, True), (None, False)]
        + [(str(digit), False) for digit in range(1, 10)]
    )
    collected: list[dict[str, Any]] = []
    failed_slices: list[str] = []
    for prefix, end_qualifier in attempts:
        query = _class_query(class_qid, prefix=prefix, end_qualifier=end_qualifier)
        try:
            bindings = sparql(query, attempts=2, timeout=90.0)
        except Exception:
            time.sleep(delay)
            if prefix is None:
                continue
            failed_slices.append(prefix)
            continue
        time.sleep(delay)
        if prefix is None:
            return rows_from_bindings(bindings, class_qid, admin_level=admin_level)
        collected.extend(rows_from_bindings(bindings, class_qid, admin_level=admin_level))
    if failed_slices:
        raise RuntimeError(f"Wikidata slices failed for {class_qid}: {','.join(failed_slices)}")
    if collected:
        return _dedupe_rows(collected)
    raise RuntimeError(f"Wikidata did not return {class_qid}")


def _dedupe_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_qid: dict[str, dict[str, Any]] = {}
    for row in rows:
        qid = str(row.get("qid") or "")
        if not qid:
            continue
        current = by_qid.get(qid)
        if current is None or (not current.get("source_urls") and row.get("source_urls")):
            by_qid[qid] = dict(row)
        elif row.get("name") and not current.get("name"):
            current["name"] = row["name"]
            current["wikidata_label"] = row["name"]
    return list(by_qid.values())


def _load_progress(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"done": [], "failed": {}, "skipped": [], "counts": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("done", [])
    payload.setdefault("failed", {})
    payload.setdefault("skipped", [])
    payload.setdefault("counts", {})
    return payload


def _save_progress(path: Path, progress: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def output_path(dest: Path, country_code: str, region: str) -> Path:
    if country_code == "US":
        return dest / "americas" / "US_wikidata.jsonl"
    if country_code == "NL":
        return dest / "europe" / "NL.jsonl"
    if not country_code:
        return dest / "unassigned" / "_no_country.jsonl"
    if region == "unassigned":
        return dest / "unassigned" / f"{country_code}.jsonl"
    return dest / region / f"{country_code}.jsonl"


def _region_for(iso: str) -> str:
    if not iso or iso == "EU":
        return "unassigned"
    try:
        return region_for_country(iso)
    except KeyError:
        return "unassigned"


def country_iso_by_qid() -> dict[str, str]:
    """Map a country item to ISO 3166-1 alpha-2, preferring a non-deprecated code."""
    query = """
SELECT ?country ?iso ?rank WHERE {
  ?country p:P297 ?stmt .
  ?stmt ps:P297 ?iso ;
        wikibase:rank ?rank .
}
"""
    ranked: dict[str, tuple[int, str]] = {}
    rank_score = {
        "http://wikiba.se/ontology#PreferredRank": 3,
        "http://wikiba.se/ontology#NormalRank": 2,
        "http://wikiba.se/ontology#DeprecatedRank": 1,
    }
    for binding in sparql(query, attempts=3, timeout=120.0):
        country = _qid(_cell(binding, "country"))
        iso = _cell(binding, "iso").upper()
        score = rank_score.get(_cell(binding, "rank"), 0)
        if not country or not iso or iso == "EU":
            continue
        current = ranked.get(country)
        if current is None or score > current[0]:
            ranked[country] = (score, iso)
    return {country: iso for country, (_score, iso) in ranked.items()}


def fill_country_codes(part_dir: Path, *, batch_size: int = 60, delay: float = 0.3) -> int:
    """Fill country codes when a class query returned the place but not P17."""
    iso_by_country = country_iso_by_qid()
    pending: list[tuple[Path, str]] = []
    for path in sorted(part_dir.glob("Q*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("qid") and not row.get("country_code"):
                    pending.append((path, str(row["qid"])))
    found: dict[str, str] = {}
    qids = sorted({qid for _path, qid in pending})
    for start in range(0, len(qids), batch_size):
        batch = qids[start : start + batch_size]
        values = " ".join(f"wd:{qid}" for qid in batch)
        query = f"""
SELECT ?item ?country WHERE {{
  VALUES ?item {{ {values} }}
  ?item wdt:P17 ?country .
}}
"""
        try:
            bindings = sparql(query, attempts=3, timeout=60.0)
        except Exception as exc:
            print(f"country lookup failed at {start}: {exc}", flush=True)
            time.sleep(delay)
            continue
        for binding in bindings:
            qid = _qid(_cell(binding, "item"))
            iso = iso_by_country.get(_qid(_cell(binding, "country")), "")
            if qid and iso and qid not in found:
                found[qid] = iso
        print(f"country lookup {min(start + batch_size, len(qids))}/{len(qids)}", flush=True)
        time.sleep(delay)
    updated = 0
    by_path: dict[Path, list[dict[str, Any]]] = {}
    for path, qid in pending:
        by_path.setdefault(path, [])
    for path in by_path:
        rows: list[dict[str, Any]] = []
        changed = False
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                iso = found.get(str(row.get("qid") or ""))
                if iso and not row.get("country_code"):
                    row["country_code"] = iso
                    row["region"] = _region_for(iso)
                    changed = True
                    updated += 1
                rows.append(row)
        if changed:
            _write_jsonl(path, rows)
    return updated


def _fetch_prefix(
    class_qid: str,
    prefix: str,
    *,
    delay: float,
    depth: int = 0,
    admin_level: str = "municipality",
) -> list[dict[str, Any]]:
    query = _class_query(class_qid, prefix=prefix, end_qualifier=False)
    try:
        bindings = sparql(query, attempts=2, timeout=90.0)
    except Exception:
        time.sleep(delay)
        if depth >= 2:
            raise
        rows: list[dict[str, Any]] = []
        failed: list[str] = []
        for digit in "0123456789":
            try:
                rows.extend(
                    _fetch_prefix(
                        class_qid,
                        prefix + digit,
                        delay=delay,
                        depth=depth + 1,
                        admin_level=admin_level,
                    )
                )
            except Exception:
                failed.append(prefix + digit)
        if failed:
            print(f"partial {class_qid} prefix {prefix} missing {','.join(failed)}", flush=True)
        if failed and not rows:
            raise RuntimeError(f"slices failed {class_qid}: {','.join(failed)}")
        return rows
    time.sleep(delay)
    return rows_from_bindings(bindings, class_qid, admin_level=admin_level)


def refetch_failed_classes(part_dir: Path, *, delay: float = 0.35) -> dict[str, int]:
    progress_path = part_dir / "progress.json"
    progress = _load_progress(progress_path)
    recovered: dict[str, int] = {}
    for class_qid in list(progress.get("failed") or {}):
        collected: list[dict[str, Any]] = []
        try:
            for digit in "123456789":
                collected.extend(_fetch_prefix(class_qid, digit, delay=delay))
                print(f"refetch {class_qid} prefix {digit} total={len(collected)}", flush=True)
        except Exception as exc:
            if collected:
                _write_jsonl(part_dir / f"{class_qid}.jsonl", _dedupe_rows(collected))
            progress["failed"][class_qid] = f"{type(exc).__name__}: {exc}"
            _save_progress(progress_path, progress)
            print(f"FAIL refetch {class_qid}: {exc}", flush=True)
            continue
        rows = _dedupe_rows(collected)
        _write_jsonl(part_dir / f"{class_qid}.jsonl", rows)
        progress["failed"].pop(class_qid, None)
        if class_qid not in progress["done"]:
            progress["done"].append(class_qid)
        progress["counts"][class_qid] = len(rows)
        _save_progress(progress_path, progress)
        recovered[class_qid] = len(rows)
        print(f"OK refetch {class_qid} rows={len(rows)}", flush=True)
    return recovered


def finalize_world(dest: Path, parts: Path) -> dict[str, Any]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    part_files = sorted(parts.glob("*.jsonl"))
    for path in part_files:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                iso = str(row.get("country_code") or "")
                qid = str(row.get("qid") or "")
                if not qid or iso == "EU":
                    continue
                bucket = grouped.setdefault(iso, {})
                current = bucket.get(qid)
                if current is None or (not current.get("source_urls") and row.get("source_urls")):
                    bucket[qid] = row
                elif row.get("name") and not current.get("name"):
                    current["name"] = row["name"]
                    current["wikidata_label"] = row["name"]
    written: dict[str, int] = {}
    preserved: list[str] = []
    for iso, rows_by_qid in sorted(grouped.items()):
        sample = next(iter(rows_by_qid.values()))
        region = str(sample.get("region") or "unassigned")
        path = output_path(dest, iso, region)
        if iso in PRESERVE_FILES and path.exists() and iso == "NL":
            preserved.append(str(path))
            written[iso] = sum(1 for _ in path.open(encoding="utf-8"))
            continue
        rows = sorted(rows_by_qid.values(), key=lambda row: (str(row.get("name") or "").lower(), row["qid"]))
        written[iso] = _write_jsonl(path, rows)
    summary = {
        "countries": len(written),
        "rows": sum(written.values()),
        "by_country": written,
        "preserved": preserved,
        "part_files": len(part_files),
    }
    report_path = dest / "world_summary.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary["report"] = str(report_path)
    return summary


def _retag_admin_level(path: Path, admin_level: str) -> int:
    if not path.is_file() or not admin_level:
        return 0
    rows: list[dict[str, Any]] = []
    changed = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("admin_level") != admin_level:
                row["admin_level"] = admin_level
                changed += 1
            rows.append(row)
    if changed:
        _write_jsonl(path, rows)
    return changed


def harvest_named_classes(
    dest: Path,
    classes: Sequence[tuple[str, str]],
    *,
    parts: Path | None = None,
    delay: float = 0.35,
    admin_level: str = "municipality",
) -> dict[str, Any]:
    """Fetch an explicit class list, skipping classes already marked done.

    admin_level "from-label" sets state, province, region, and the other
    first-level names from the class label. An already fetched class is
    relabeled and not downloaded again.
    """
    part_dir = parts or parts_root()
    part_dir.mkdir(parents=True, exist_ok=True)
    progress_path = part_dir / "progress.json"
    progress = _load_progress(progress_path)
    done = set(progress["done"])
    print(f"classes {len(classes)} done {len(done)}", flush=True)
    for index, (qid, label) in enumerate(classes, start=1):
        level = admin_level_for_label(label) if admin_level == "from-label" else admin_level
        if qid in done:
            updated = _retag_admin_level(part_dir / f"{qid}.jsonl", level if admin_level == "from-label" else "")
            if updated:
                print(f"RETAG {index}/{len(classes)} {qid} {label} {level} rows={updated}", flush=True)
            continue
        if skip_class_label(label):
            print(f"SKIP {index}/{len(classes)} {qid} {label}", flush=True)
            continue
        part_path = part_dir / f"{qid}.jsonl"
        try:
            rows = fetch_class_rows(qid, delay=delay, admin_level=level)
        except Exception as exc:
            progress["failed"][qid] = f"{label}: {type(exc).__name__}: {exc}"
            _save_progress(progress_path, progress)
            print(f"FAIL {index}/{len(classes)} {qid} {label}: {exc}", flush=True)
            continue
        _write_jsonl(part_path, rows)
        if qid not in done:
            progress["done"].append(qid)
            done.add(qid)
        progress["failed"].pop(qid, None)
        progress["counts"][qid] = len(rows)
        _save_progress(progress_path, progress)
        print(f"OK {index}/{len(classes)} {qid} {label} rows={len(rows)}", flush=True)
    summary = finalize_world(dest, part_dir)
    summary["failed"] = progress["failed"]
    summary["classes_done"] = len(progress["done"])
    _save_progress(progress_path, progress)
    return summary


def harvest_world(
    dest: Path,
    *,
    parts: Path | None = None,
    delay: float = 0.35,
    class_limit: int | None = None,
    only_class: str = "",
) -> dict[str, Any]:
    part_dir = parts or parts_root()
    part_dir.mkdir(parents=True, exist_ok=True)
    progress_path = part_dir / "progress.json"
    progress = _load_progress(progress_path)
    done = set(progress["done"])
    classes = municipality_classes()
    if only_class:
        classes = [item for item in classes if item[0] == only_class]
        if not classes:
            classes = [(only_class, only_class)]
    if class_limit is not None:
        classes = classes[:class_limit]
    print(f"classes {len(classes)} done {len(done)}", flush=True)
    for index, (qid, label) in enumerate(classes, start=1):
        if qid in done and not only_class:
            continue
        part_path = part_dir / f"{qid}.jsonl"
        try:
            rows = fetch_class_rows(qid, delay=delay)
        except Exception as exc:
            progress["failed"][qid] = f"{label}: {type(exc).__name__}: {exc}"
            _save_progress(progress_path, progress)
            print(f"FAIL {index}/{len(classes)} {qid} {label}: {exc}", flush=True)
            continue
        _write_jsonl(part_path, rows)
        if qid not in done:
            progress["done"].append(qid)
            done.add(qid)
        progress["failed"].pop(qid, None)
        progress["counts"][qid] = len(rows)
        _save_progress(progress_path, progress)
        print(f"OK {index}/{len(classes)} {qid} {label} rows={len(rows)}", flush=True)
    summary = finalize_world(dest, part_dir)
    summary["failed"] = progress["failed"]
    summary["classes_done"] = len(progress["done"])
    _save_progress(progress_path, progress)
    return summary
