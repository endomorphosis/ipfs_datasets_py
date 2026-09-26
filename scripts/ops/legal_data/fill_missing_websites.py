#!/usr/bin/env python3
"""Write the no-website countries and search Wikipedia for official sites.

The subset is every place in a country where no row has a source URL.
Wikidata is checked again for any rank of P856. The rest use the English
Wikipedia infobox. Found sites are written back onto the seed rows.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    text = str(repo_root)
    if text not in sys.path:
        sys.path.insert(0, text)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_scrapers.municipal.population import sort_by_population  # noqa: E402
from ipfs_datasets_py.processors.legal_scrapers.municipal.seed_harvest import (  # noqa: E402
    classify_urls,
    seed_root,
)
from ipfs_datasets_py.processors.legal_scrapers.municipal.websites import (  # noqa: E402
    clean_website,
    official_website_from_wikitext,
)
from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import (  # noqa: E402
    _cell,
    _qid,
    parts_root,
    sparql,
)

UA = "JusticeDAO-MunicipalSeed/1.0 (+https://huggingface.co/datasets/endomorphosis/american_municipal_law)"
SKIP_NAMES = {"us_gnis_crosswalk.jsonl", "traverse_journal.jsonl", "US_wikidata.jsonl"}


def seed_files(dest: Path) -> list[Path]:
    found = []
    for path in sorted(dest.rglob("*.jsonl")):
        if any(part in path.parts for part in ("code_hosts", "code_docs", "missing_urls")):
            continue
        if path.name in SKIP_NAMES:
            continue
        found.append(path)
    return found


def zero_url_places(files: list[Path]) -> tuple[set[str], list[dict]]:
    by_country: dict[str, list[dict]] = {}
    for path in files:
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            iso = str(row.get("country_code") or "")
            if not iso:
                continue
            by_country.setdefault(iso, []).append(row)
    countries = {iso for iso, rows in by_country.items() if rows and not any(row.get("source_urls") for row in rows)}
    places = [row for iso in countries for row in by_country[iso] if not row.get("source_urls")]
    return countries, sort_by_population(places)


def lookup_query(qids: list[str]) -> str:
    values = " ".join(f"wd:{qid}" for qid in qids)
    return f"""
SELECT ?item ?site ?article WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{
    ?item p:P856 ?statement .
    ?statement ps:P856 ?site .
  }}
  OPTIONAL {{
    ?article schema:about ?item .
    ?article schema:isPartOf <https://en.wikipedia.org/> .
  }}
}}
"""


def wikipedia_title(article: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(article)
    title = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
    return parsed.netloc or "en.wikipedia.org", title.replace("_", " ")


def fetch_wikitext(host: str, title: str) -> str:
    query = urllib.parse.urlencode(
        {
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": title,
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
        }
    )
    request = urllib.request.Request(f"https://{host}/w/api.php?{query}", headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.loads(response.read().decode())
    pages = data.get("query", {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        return ""
    revisions = pages[0].get("revisions") or [{}]
    return str(revisions[0].get("slots", {}).get("main", {}).get("content") or "")


def search_places(places: list[dict], *, delay: float) -> dict[str, str]:
    found: dict[str, str] = {}
    articles: dict[str, str] = {}
    qids = [str(row.get("qid") or "") for row in places if row.get("qid")]
    for start in range(0, len(qids), 60):
        batch = qids[start : start + 60]
        try:
            bindings = sparql(lookup_query(batch), attempts=3, timeout=60.0)
        except Exception as exc:
            print(f"SPARQL FAIL {batch[0]} {type(exc).__name__}", flush=True)
            continue
        for binding in bindings:
            qid = _qid(_cell(binding, "item"))
            site = clean_website(_cell(binding, "site"))
            article = _cell(binding, "article")
            if qid and site and qid not in found:
                found[qid] = site
            elif qid and article and qid not in articles:
                articles[qid] = article
        print(f"lookup {min(start + 60, len(qids))}/{len(qids)} p856 {len(found)} wiki {len(articles)}", flush=True)
        time.sleep(delay)
    pending = [qid for qid in qids if qid not in found and qid in articles]
    print(f"wikipedia pages {len(pending)}", flush=True)
    for index, qid in enumerate(pending, start=1):
        host, title = wikipedia_title(articles[qid])
        try:
            text = fetch_wikitext(host, title)
            site = official_website_from_wikitext(text)
        except Exception as exc:
            print(f"WIKI FAIL {qid} {type(exc).__name__}", flush=True)
            site = ""
        if site:
            found[qid] = site
        if index % 25 == 0 or index == len(pending):
            print(f"wiki {index}/{len(pending)} found {len(found)}", flush=True)
        time.sleep(delay)
    return found


def apply_sites(paths: list[Path], sites: dict[str, str]) -> int:
    updated = 0
    for path in paths:
        rows = []
        changed = False
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            site = sites.get(str(row.get("qid") or ""))
            if site and not row.get("source_urls"):
                row["source_urls"] = [site]
                url_class, publisher = classify_urls([site])
                row["url_class"] = url_class
                row["publisher"] = publisher
                changed = True
                updated += 1
            rows.append(row)
        if not changed:
            continue
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        temporary.replace(path)
    return updated


def main() -> int:
    dest = seed_root()
    files = seed_files(dest)
    countries, places = zero_url_places(files)
    out = dest / "missing_urls"
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "countries": sorted(countries),
        "country_count": len(countries),
        "places": len(places),
    }
    (out / "countries.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (out / "places.jsonl").open("w", encoding="utf-8") as handle:
        for row in places:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"subset countries {len(countries)} places {len(places)}", flush=True)
    sites = search_places(places, delay=0.15)
    (out / "found.json").write_text(json.dumps(sites, indent=2) + "\n", encoding="utf-8")
    parts = list(parts_root().glob("*.jsonl")) if parts_root().is_dir() else []
    written = apply_sites(files + parts, sites)
    print(json.dumps({"countries": len(countries), "places": len(places), "found": len(sites), "rows_updated": written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
