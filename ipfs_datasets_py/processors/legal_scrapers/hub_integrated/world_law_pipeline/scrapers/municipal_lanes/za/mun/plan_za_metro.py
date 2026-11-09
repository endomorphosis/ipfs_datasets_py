#!/usr/bin/env python3
"""Scope filter + pre-fetch dedupe of catalog.json against the LIVE repo (all CPT/JHB rows incl. *_html AKN works and
laws-* shards): normalised URL, and (core by-law name, year) where the year is known from the listing/filename.
Undated candidates are fetched and deduped again on the masthead title in stage. Env ZA_WORK."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import json, os, re, unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit
import pyarrow.parquet as pq
W = Path(os.environ.get("ZA_WORK", (str(_LEGAL_WS) + "/world_laws/za_metro")))
def fold(s): return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
def nurl(u):
    s = urlsplit(unquote(u or "")); return ((s.hostname or "").removeprefix("www.") + s.path.rstrip("/")).lower()
STOP = r"\b(city of cape town|city of johannesburg|cape town|johannesburg|cct|coj|prom|promulgated|gazette|gazetted|final|english|the|of|and|to|relating|by ?laws?|bylaws?|by law|doc)\b"
def year(s):
    y = re.findall(r"(?<!\d)(19[5-9]\d|20[0-3]\d)(?!\d)", s or ""); return int(y[-1]) if y else None
def core(s):
    f = re.sub(r"[_\-%]+", " ", fold(unquote(s or ""))); f = re.sub(r"\.pdf$", "", f)
    f = re.sub(r"(?<!\d)(19|20)\d\d(?!\d)", " ", f); f = re.sub(r"\(.*?\)", " ", f)
    f = re.sub(r"\b(first|second|third|further|amended|amendment|amendments|january|february|march|april|may|june|july|august|september|october|november|december|published|as)\b", " ", f)
    f = re.sub(r"\bsub\s*-?\s*councils?\b|\bsubcouncils\b", "subcouncil", f)
    f = re.sub(STOP, " ", f); f = re.sub(r"[^a-z ]+", " ", f)
    w = [x for x in f.split() if len(x) > 1]; return " ".join(w)
def is_amend(s): return bool(re.search(r"amend", fold(s)))
OUT = re.compile(r"polic|strategy|plan\b|aqmp|framework|rules|tor\b|terms of reference|membership|guideline|draft|for comment|"
                 r"public comment|tariffs? (?:list|schedule)|annexure|vehicle emissions|delegation|charter|spatial|manual|form\b", re.I)
def live_keys():
    keys, urls = {}, set()
    d = Path(W / "tip/data")
    for c in ("CPT", "JHB"):
        t = pq.read_table(d / f"{c}_html.parquet", columns=["title", "source_url", "regeling_work_id"]).to_pylist()
        for r in t:
            urls.add(nurl(r["source_url"])); y = year(r["title"]) or year(r["regeling_work_id"])
            keys[(c.lower(), core(r["title"]), y)] = r["title"]
    for f in sorted(d.glob("laws-*.parquet")):
        for r in pq.read_table(f, columns=["title", "source_url", "municipality_id"]).to_pylist():
            urls.add(nurl(r["source_url"]))
            if r["municipality_id"] in ("za-cpt", "za-jhb"):
                keys[(r["municipality_id"][3:], core(r["title"]), year(r["title"]))] = r["title"]
    return keys, urls
def main():
    keys, urls = live_keys(); todo, exc, seen = [], [], {}
    for it in json.load(open(W / "catalog.json")):
        name = it["filename"]; lab = it.get("title") or ""; city = it["src"]
        y = year(lab) or year(name); k = core(name); kl = core(lab)
        r = None
        if not re.search(r"by.?law", fold(name + " " + lab)) and not re.search(r"ilovepdf_merged", name): r = "out_of_scope_not_bylaw"
        elif OUT.search(name) or OUT.search(lab): r = "out_of_scope_policy_or_draft_or_non_law"
        elif nurl(it["url"]) in urls: r = "dup_live_url"
        elif y and ((city, k, y) in keys or (city, kl, y) in keys): r = "dup_live_name_year"
        elif (city, k, y, is_amend(name)) in seen: r = "dup_in_catalog"
        if r:
            exc.append({"ident": it["ident"], "url": it["url"], "filename": name, "listing_title": lab, "reason": r, "key": [city, k, y], **({"matched": (OUT.search(name) or OUT.search(lab)).group(0)} if r.startswith("out_of_scope_policy") else {}),
                        **({"live_title": keys.get((city, k, y)) or keys.get((city, kl, y))} if r == "dup_live_name_year" else {})}); continue
        seen[(city, k, y, is_amend(name))] = it["ident"]; todo.append(it["ident"])
    json.dump(todo, open(W / "todo.json", "w"), indent=0)
    with open(W / "listing_exclusions.jsonl", "w") as fh:
        for e in exc: fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    print("todo", len(todo), dict(Counter(i.split("-")[0] for i in todo)), dict(Counter(e["reason"] for e in exc)), "live_keys", len(keys))
if __name__ == "__main__": main()
