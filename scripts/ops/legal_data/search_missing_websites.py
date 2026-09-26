#!/usr/bin/env python3
"""Search DuckDuckGo for official sites of places that still have none.

Only countries that already have some websites are included. A result is
kept when the place name is in the address or the host is a government
domain. Progress is appended to seeds/missing_urls/search_engine.jsonl.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    text = str(repo_root)
    if text not in sys.path:
        sys.path.insert(0, text)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_scrapers.municipal.population import sort_municipalities_first  # noqa: E402
from ipfs_datasets_py.processors.legal_scrapers.municipal.seed_harvest import classify_urls, seed_root  # noqa: E402
from ipfs_datasets_py.processors.legal_scrapers.municipal.websites import result_matches_place  # noqa: E402
from ipfs_datasets_py.processors.legal_scrapers.municipal.world_seed import parts_root  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
SKIP_NAMES = {"us_gnis_crosswalk.jsonl", "traverse_journal.jsonl", "US_wikidata.jsonl"}


def country_names() -> dict[str, str]:
    path = Path("/usr/share/iso-codes/json/iso_3166-1.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["alpha_2"]: row["name"] for row in data["3166-1"] if row.get("alpha_2") and row.get("name")}


def seed_files(dest: Path) -> list[Path]:
    found = []
    for path in sorted(dest.rglob("*.jsonl")):
        if any(part in path.parts for part in ("code_hosts", "code_docs", "missing_urls")):
            continue
        if path.name in SKIP_NAMES:
            continue
        found.append(path)
    return found


def places_missing_sites(files: list[Path], skip_countries: set[str]) -> list[dict]:
    rows = []
    for path in files:
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            iso = str(row.get("country_code") or "")
            if not iso or iso in skip_countries or row.get("source_urls") or not row.get("qid"):
                continue
            rows.append(row)
    return sort_municipalities_first(rows)


def load_done(path: Path) -> set[str]:
    found: set[str] = set()
    if not path.is_file():
        return found
    for line in path.open(encoding="utf-8"):
        if line.strip():
            found.add(str(json.loads(line).get("qid") or ""))
    return found


def brave_key() -> str:
    return os.environ.get("BRAVE_SEARCH_API_KEY") or os.environ.get("BRAVE_API_KEY") or ""


def search_links(query: str) -> list[str]:
    """Brave Search API. https://api.search.brave.com/res/v1/web/search"""
    token = brave_key()
    if not token:
        raise RuntimeError("Set BRAVE_API_KEY or BRAVE_SEARCH_API_KEY")
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": 8, "search_lang": "en"}
    )
    pause = 2.0
    payload: dict = {}
    for attempt in range(4):
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "X-Subscription-Token": token, "User-Agent": UA},
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read().decode())
            break
        except urllib.error.HTTPError as exc:
            if exc.code in {429, 503} and attempt < 3:
                time.sleep(pause)
                pause *= 2
                continue
            raise
    seen: list[str] = []
    for item in (payload.get("web") or {}).get("results") or []:
        link = str(item.get("url") or "")
        if link.startswith("http") and link not in seen:
            seen.append(link)
        if len(seen) >= 8:
            break
    return seen


def pick_site(links: list[str], name: str) -> str:
    for link in links:
        if result_matches_place(link, name):
            return link.split("?", 1)[0]
    return ""


def _apply_journal(dest: Path, files: list[Path], journal_path: Path) -> int:
    sites: dict[str, str] = {}
    if journal_path.is_file():
        for line in journal_path.open(encoding="utf-8"):
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("url"):
                sites[str(item["qid"])] = str(item["url"])
    parts = list(parts_root().glob("*.jsonl")) if parts_root().is_dir() else []
    return apply_sites(files + parts, sites)


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
    names = country_names()
    zero = set()
    countries_path = dest / "missing_urls" / "countries.json"
    if countries_path.is_file():
        zero = set(json.loads(countries_path.read_text(encoding="utf-8")).get("countries") or [])
    files = seed_files(dest)
    places = places_missing_sites(files, zero)
    journal_path = dest / "missing_urls" / "search_engine.jsonl"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done(journal_path)
    pending = [row for row in places if str(row.get("qid")) not in done]
    subset = dest / "missing_urls" / "partial_countries.jsonl"
    if not subset.is_file():
        with subset.open("w", encoding="utf-8") as handle:
            for row in places:
                handle.write(json.dumps({"qid": row.get("qid"), "name": row.get("name"), "country_code": row.get("country_code"), "population": row.get("population"), "admin_level": row.get("admin_level")}, ensure_ascii=False) + "\n")
    print(f"search pending {len(pending)} already {len(done)} of {len(places)}", flush=True)
    found = 0
    with journal_path.open("a", encoding="utf-8") as journal:
        for index, row in enumerate(pending, start=1):
            qid = str(row["qid"])
            name = str(row.get("name") or "")
            country = names.get(str(row.get("country_code") or ""), str(row.get("country_code") or ""))
            query = f"\"{name}\" {country} official website"
            site = ""
            error = ""
            try:
                site = pick_site(search_links(query), name)
            except Exception as exc:
                print(f"STOP {qid} {type(exc).__name__}: {exc}", flush=True)
                journal.flush()
                updated = _apply_journal(dest, files, journal_path)
                print(json.dumps({"stopped": qid, "found_this_run": found, "searched": index - 1, "rows_updated": updated}, indent=2))
                return 1
            if site:
                found += 1
            journal.write(json.dumps({"qid": qid, "name": name, "country_code": row.get("country_code"), "url": site, "error": error}, ensure_ascii=False) + "\n")
            if index % 10 == 0:
                journal.flush()
            if index % 25 == 0 or index == len(pending):
                print(f"search {index}/{len(pending)} found {found}", flush=True)
            time.sleep(1.5)
    updated = _apply_journal(dest, files, journal_path)
    print(json.dumps({"pending": len(pending), "found_this_run": found, "rows_updated": updated}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
