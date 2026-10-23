"""Build municipal seed rows from the US GNIS inventory and Wikidata.

The global key is a Wikidata QID. GNIS stays the United States key and joins
through property P590. Official websites come from truthy P856 statements.
Scraping status on existing US rows is copied through unchanged.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.legal_scrapers.regions.mapping import region_for_country

WDQS = "https://query.wikidata.org/sparql"
USER_AGENT = (
    "JusticeDAO-MunicipalSeed/1.0 "
    "(+https://huggingface.co/datasets/endomorphosis/american_municipal_law)"
)

# Host suffix, publisher id. First matching URL in row order wins.
CODE_HOSTS: tuple[tuple[str, str], ...] = (
    ("municode.com", "municode"),
    ("amlegal.com", "amlegal"),
    ("ecode360.com", "ecode360"),
    ("codepublishing.com", "codepublishing"),
)

# Netherlands pilot. Water boards (Q13138621) are a separate board, not a
# province or municipality, and stay out of this seed. Q3648563 ("public body
# of the Netherlands") also matches the national government, so the Caribbean
# islands are taken from Q3237519 instead.
NL_CLASSES: tuple[tuple[str, str], ...] = (
    ("Q134390", "adm1"),
    ("Q2039348", "municipality"),
    ("Q3237519", "municipality"),
)
NL_PORTAL = "https://lokaleregelgeving.overheid.nl/"

_COUNTY_RE = re.compile(r"\b(county|parish)\b", re.I)
_CITY_RE = re.compile(r"\b(city|town|village|borough|township)\b", re.I)


def seed_root(start: Path | None = None) -> Path:
    if start is not None:
        return start
    return Path(__file__).resolve().parent / "seeds"


def host_of(url: str) -> str:
    try:
        netloc = urllib.parse.urlparse(url.strip()).netloc.lower()
    except ValueError:
        return ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def publisher_for_url(url: str) -> str:
    host = host_of(url)
    if not host:
        return ""
    for suffix, publisher in CODE_HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return publisher
    return ""


def classify_urls(urls: Sequence[str]) -> tuple[str, str]:
    """Return (url_class, publisher). Publisher is empty unless url_class is code_host."""
    cleaned = [url for url in urls if url]
    if not cleaned:
        return "none", ""
    for url in cleaned:
        publisher = publisher_for_url(url)
        if publisher:
            return "code_host", publisher
    return "official_site", ""


def us_admin_level(place_name: str) -> str:
    if _CITY_RE.search(place_name or ""):
        return "municipality"
    if _COUNTY_RE.search(place_name or ""):
        return "adm2"
    return "municipality"


def split_urls(row: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    raw = row.get("source_urls")
    if isinstance(raw, list):
        found.extend(str(item) for item in raw)
    elif isinstance(raw, str) and raw.strip():
        found.extend(part.strip() for part in raw.split(","))
    single = row.get("source_url")
    if isinstance(single, str) and single.strip():
        found.extend(part.strip() for part in single.split(","))
    out: list[str] = []
    seen: set[str] = set()
    for url in found:
        url = url.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _qid(uri: str) -> str:
    text = (uri or "").rstrip("/")
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def _cell(binding: Mapping[str, Any], key: str) -> str:
    cell = binding.get(key)
    if not isinstance(cell, dict):
        return ""
    return str(cell.get("value") or "")


def _split_pipe(value: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in (value or "").split("|"):
        part = part.strip()
        if not part or part in seen:
            continue
        seen.add(part)
        out.append(part)
    return out


def sparql(query: str, *, attempts: int = 5, timeout: float = 90.0) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    payload = query.encode("utf-8")
    for attempt in range(attempts):
        request = urllib.request.Request(
            WDQS,
            data=payload,
            headers={
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/sparql-query; charset=utf-8",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            bindings = data.get("results", {}).get("bindings", [])
            if not isinstance(bindings, list):
                return []
            return bindings
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise
            time.sleep(min(30.0, 2.0 * (2**attempt)))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise
            time.sleep(min(30.0, 2.0 * (2**attempt)))
    if last_error:
        raise last_error
    return []


def _values(items: Sequence[str], *, quote: bool) -> str:
    if quote:
        return " ".join(json.dumps(str(item)) for item in items)
    return " ".join(f"wd:{item}" for item in items)


def lookup_gnis_batch(gnis_ids: Sequence[str]) -> list[dict[str, str]]:
    values = _values(gnis_ids, quote=True)
    query = f"""
SELECT ?item ?gnis ?en ?iso WHERE {{
  VALUES ?gnis {{ {values} }}
  ?item wdt:P590 ?gnis .
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{
    ?item wdt:P17 ?country .
    ?country wdt:P297 ?iso .
  }}
}}
"""
    rows: list[dict[str, str]] = []
    for binding in sparql(query):
        rows.append(
            {
                "qid": _qid(_cell(binding, "item")),
                "gnis": _cell(binding, "gnis"),
                "label": _cell(binding, "en"),
                "country_code": _cell(binding, "iso").upper(),
            }
        )
    return rows


def enrich_items(qids: Sequence[str]) -> dict[str, dict[str, Any]]:
    if not qids:
        return {}
    values = _values(qids, quote=False)
    query = f"""
SELECT ?item
  (GROUP_CONCAT(DISTINCT ?gnis; separator="|") AS ?gnises)
  (GROUP_CONCAT(DISTINCT STR(?website); separator="|") AS ?sites)
  (GROUP_CONCAT(DISTINCT ?geonames; separator="|") AS ?geonamesIds)
  (GROUP_CONCAT(DISTINCT ?langCode; separator="|") AS ?langs)
  (SAMPLE(?parent) AS ?parent)
  (SAMPLE(?iso2) AS ?iso2)
  (SAMPLE(?lat) AS ?lat)
  (SAMPLE(?lon) AS ?lon)
  (SAMPLE(STR(?pop)) AS ?population)
  (SAMPLE(?official) AS ?official)
WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{ ?item wdt:P590 ?gnis }}
  OPTIONAL {{ ?item wdt:P856 ?website }}
  OPTIONAL {{ ?item wdt:P1566 ?geonames }}
  OPTIONAL {{ ?item wdt:P131 ?parent }}
  OPTIONAL {{ ?item wdt:P300 ?iso2 }}
  OPTIONAL {{ ?item wdt:P1082 ?pop }}
  OPTIONAL {{ ?item wdt:P1448 ?official FILTER(LANG(?official) = "en") }}
  OPTIONAL {{
    ?item wdt:P37 ?langItem .
    ?langItem wdt:P218 ?langCode .
  }}
  OPTIONAL {{
    ?item p:P625 ?stmt .
    ?stmt psv:P625 ?node .
    ?node wikibase:geoLatitude ?lat ;
          wikibase:geoLongitude ?lon .
  }}
}}
GROUP BY ?item
"""
    found: dict[str, dict[str, Any]] = {}
    for binding in sparql(query):
        qid = _qid(_cell(binding, "item"))
        if not qid:
            continue
        found[qid] = {
            "gnises": _split_pipe(_cell(binding, "gnises")),
            "sites": _split_pipe(_cell(binding, "sites")),
            "geonames_ids": _split_pipe(_cell(binding, "geonamesIds")),
            "langs": _split_pipe(_cell(binding, "langs")),
            "parent_qid": _qid(_cell(binding, "parent")),
            "iso_3166_2": _cell(binding, "iso2"),
            "lat": _cell(binding, "lat"),
            "lon": _cell(binding, "lon"),
            "population": _cell(binding, "population"),
            "official_name": _cell(binding, "official"),
        }
    return found


def load_us_seed(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict) and payload.get("gnis") is not None:
                rows.append(payload)
    return rows


def _number(value: str) -> float | None:
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def build_us_row(
    seed: Mapping[str, Any],
    hits: Sequence[Mapping[str, str]],
    extras: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    gnis = str(seed.get("gnis"))
    by_qid: dict[str, Mapping[str, str]] = {}
    for hit in hits:
        qid = str(hit.get("qid") or "")
        if qid:
            by_qid[qid] = hit
    qids = sorted(by_qid)
    match = "unmatched"
    chosen = ""
    if len(qids) == 1:
        match = "matched"
        chosen = qids[0]
    elif len(qids) > 1:
        match = "ambiguous"
    extra = extras.get(chosen, {}) if chosen else {}
    seed_urls = split_urls(seed)
    wiki_urls = [url for url in extra.get("sites", []) if url not in seed_urls]
    source_urls = seed_urls + wiki_urls
    url_class, publisher = classify_urls(source_urls)
    gnis_alt = [item for item in extra.get("gnises", []) if item and item != gnis]
    country = ""
    label = ""
    if chosen:
        country = str(by_qid[chosen].get("country_code") or "US")
        label = str(by_qid[chosen].get("label") or "")
    else:
        country = "US"
    try:
        region = region_for_country(country)
    except KeyError:
        region = "americas"
        country = country or "US"
    place_name = str(seed.get("place_name") or label)
    return {
        "qid": chosen,
        "qids": qids,
        "match": match,
        "gnis": gnis,
        "gnis_alt": gnis_alt,
        "geonames_id": (extra.get("geonames_ids") or [""])[0] if extra.get("geonames_ids") else "",
        "name": place_name,
        "wikidata_label": label,
        "official_name": extra.get("official_name") or "",
        "country_code": country,
        "region": region,
        "admin_level": us_admin_level(place_name),
        "parent_qid": extra.get("parent_qid") or "",
        "iso_3166_2": extra.get("iso_3166_2") or "",
        "state_code": str(seed.get("state_code") or ""),
        "lat": _number(str(extra.get("lat") or "")),
        "lon": _number(str(extra.get("lon") or "")),
        "population": extra.get("population") or "",
        "source_urls": source_urls,
        "wikidata_urls": list(extra.get("sites") or []),
        "url_class": url_class,
        "publisher": publisher,
        "status": str(seed.get("status") or "not_scraped"),
        "lang": list(extra.get("langs") or []),
    }


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def _batched(items: Sequence[str], size: int) -> Iterable[list[str]]:
    step = max(1, size)
    for start in range(0, len(items), step):
        yield list(items[start : start + step])


def harvest_us(
    seed_path: Path,
    dest: Path,
    *,
    batch_size: int = 80,
    delay: float = 0.6,
    limit: int | None = None,
) -> dict[str, Any]:
    seeds = load_us_seed(seed_path)
    if limit is not None:
        seeds = seeds[:limit]
    gnis_ids = [str(row.get("gnis")) for row in seeds]
    hits_by_gnis: dict[str, list[dict[str, str]]] = {gnis: [] for gnis in gnis_ids}
    batches = list(_batched(gnis_ids, batch_size))
    for index, batch in enumerate(batches, start=1):
        for hit in lookup_gnis_batch(batch):
            hits_by_gnis.setdefault(hit["gnis"], []).append(hit)
        print(f"gnis lookup {index}/{len(batches)}", flush=True)
        time.sleep(delay)
    qids = sorted({hit["qid"] for hits in hits_by_gnis.values() for hit in hits if hit.get("qid")})
    extras: dict[str, dict[str, Any]] = {}
    enrich_batches = list(_batched(qids, max(20, batch_size // 2)))
    for index, batch in enumerate(enrich_batches, start=1):
        extras.update(enrich_items(batch))
        print(f"qid enrich {index}/{len(enrich_batches)}", flush=True)
        time.sleep(delay)
    rows = [build_us_row(seed, hits_by_gnis.get(str(seed.get("gnis")), []), extras) for seed in seeds]
    rows.sort(key=lambda row: (row["state_code"], row["name"].lower(), row["gnis"]))
    us_path = dest / "americas" / "US.jsonl"
    cross_path = dest / "us_gnis_crosswalk.jsonl"
    _write_jsonl(us_path, rows)
    _write_jsonl(
        cross_path,
        (
            {
                "gnis": row["gnis"],
                "qid": row["qid"],
                "qids": row["qids"],
                "match": row["match"],
                "gnis_alt": row["gnis_alt"],
                "wikidata_label": row["wikidata_label"],
                "state_code": row["state_code"],
                "name": row["name"],
            }
            for row in rows
        ),
    )
    return {"rows": rows, "us_path": us_path, "crosswalk_path": cross_path}


def harvest_netherlands(dest: Path, *, delay: float = 0.6) -> dict[str, Any]:
    values = " ".join(f"wd:{qid}" for qid, _level in NL_CLASSES)
    level_binds = " ".join(
        f'IF(?class = wd:{qid}, "{level}",' for qid, level in NL_CLASSES
    )
    # Nested IF() chain closed by the same number of parentheses, defaulting
    # to municipality if a class is added without a level.
    level_expr = level_binds + ' "municipality"' + (")" * len(NL_CLASSES))
    query = f"""
SELECT ?item ?class ?level
  (SAMPLE(?en) AS ?enLabel)
  (SAMPLE(?nl) AS ?nlLabel)
  (GROUP_CONCAT(DISTINCT STR(?site); separator="|") AS ?sites)
  (GROUP_CONCAT(DISTINCT ?geonames; separator="|") AS ?geonamesIds)
  (GROUP_CONCAT(DISTINCT ?langCode; separator="|") AS ?langs)
  (SAMPLE(?parent) AS ?parent)
  (SAMPLE(?iso2) AS ?iso2)
  (SAMPLE(?lat) AS ?lat)
  (SAMPLE(?lon) AS ?lon)
  (SAMPLE(STR(?pop)) AS ?population)
WHERE {{
  VALUES ?class {{ {values} }}
  ?item p:P31 ?classStmt .
  ?classStmt ps:P31 ?class .
  FILTER NOT EXISTS {{ ?classStmt pq:P582 ?end }}
  FILTER NOT EXISTS {{ ?item wdt:P576 ?dissolved }}
  BIND({level_expr} AS ?level)
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item rdfs:label ?nl FILTER(LANG(?nl) = "nl") }}
  OPTIONAL {{ ?item wdt:P856 ?site }}
  OPTIONAL {{ ?item wdt:P1566 ?geonames }}
  OPTIONAL {{ ?item wdt:P300 ?iso2 }}
  OPTIONAL {{ ?item wdt:P131 ?parent }}
  OPTIONAL {{ ?item wdt:P1082 ?pop }}
  OPTIONAL {{
    ?item wdt:P37 ?langItem .
    ?langItem wdt:P218 ?langCode .
  }}
  OPTIONAL {{
    ?item p:P625 ?stmt .
    ?stmt psv:P625 ?node .
    ?node wikibase:geoLatitude ?lat ;
          wikibase:geoLongitude ?lon .
  }}
}}
GROUP BY ?item ?class ?level
"""
    bindings = sparql(query, timeout=120.0)
    time.sleep(delay)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for binding in bindings:
        qid = _qid(_cell(binding, "item"))
        if not qid or qid in seen:
            continue
        seen.add(qid)
        sites = _split_pipe(_cell(binding, "sites"))
        url_class, publisher = classify_urls(sites)
        en_label = _cell(binding, "enLabel")
        nl_label = _cell(binding, "nlLabel")
        geonames_ids = _split_pipe(_cell(binding, "geonamesIds"))
        rows.append(
            {
                "qid": qid,
                "gnis": "",
                "gnis_alt": [],
                "geonames_id": geonames_ids[0] if geonames_ids else "",
                "name": en_label or nl_label,
                "wikidata_label": en_label,
                "official_name": nl_label,
                "country_code": "NL",
                "region": region_for_country("NL"),
                "admin_level": _cell(binding, "level") or "municipality",
                "wikidata_class": _qid(_cell(binding, "class")),
                "parent_qid": _qid(_cell(binding, "parent")),
                "iso_3166_2": _cell(binding, "iso2"),
                "lat": _number(_cell(binding, "lat")),
                "lon": _number(_cell(binding, "lon")),
                "population": _cell(binding, "population"),
                "source_urls": sites,
                "url_class": url_class,
                "publisher": publisher,
                "status": "not_scraped",
                "lang": _split_pipe(_cell(binding, "langs")),
            }
        )
    rows.sort(key=lambda row: (row["admin_level"], row["name"].lower(), row["qid"]))
    path = dest / "europe" / "NL.jsonl"
    _write_jsonl(path, rows)
    return {"rows": rows, "path": path, "code_portal": NL_PORTAL}


def _host_counts(urls: Iterable[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for url in urls:
        host = host_of(url)
        if host:
            counts[host] += 1
    return counts


def summarize(
    us_rows: Sequence[Mapping[str, Any]],
    nl_rows: Sequence[Mapping[str, Any]],
    *,
    us_seeds: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    match_counts = Counter(str(row.get("match") or "") for row in us_rows)
    second = sum(1 for row in us_rows if row.get("gnis_alt"))
    wiki_hosts = _host_counts(
        url for row in us_rows for url in row.get("wikidata_urls") or []
    )
    known = {suffix for suffix, _publisher in CODE_HOSTS}
    new_hosts = {
        host: count
        for host, count in wiki_hosts.most_common()
        if not any(host == suffix or host.endswith("." + suffix) for suffix in known)
    }
    seeds_by_gnis = {str(row.get("gnis")): row for row in us_seeds or []}
    added = 0
    for row in us_rows:
        seed = seeds_by_gnis.get(str(row.get("gnis")))
        seed_hosts = {host_of(url) for url in split_urls(seed)} if seed is not None else set()
        if seed is None:
            continue
        for url in row.get("wikidata_urls") or []:
            host = host_of(url)
            if host and host not in seed_hosts:
                added += 1
                break
    nl_levels = Counter(str(row.get("admin_level") or "") for row in nl_rows)
    nl_class = Counter(str(row.get("url_class") or "") for row in nl_rows)
    nl_wikidata_class = Counter(str(row.get("wikidata_class") or "") for row in nl_rows)
    return {
        "us_rows": len(us_rows),
        "us_match": dict(match_counts),
        "us_with_second_gnis": second,
        "us_distinct_qids": len({row.get("qid") for row in us_rows if row.get("qid")}),
        "us_p856_host_count": len(wiki_hosts),
        "us_p856_hosts_outside_known_code_hosts": dict(list(new_hosts.items())[:40]),
        "us_rows_with_p856_host_not_already_in_seed": added,
        "nl_rows": len(nl_rows),
        "nl_admin_level": dict(nl_levels),
        "nl_wikidata_class": dict(nl_wikidata_class),
        "nl_url_class": dict(nl_class),
        "nl_code_portal": NL_PORTAL,
        "nl_water_boards_excluded": "Q13138621",
    }


def write_report(dest: Path, report: Mapping[str, Any]) -> Path:
    path = dest / "harvest_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path
