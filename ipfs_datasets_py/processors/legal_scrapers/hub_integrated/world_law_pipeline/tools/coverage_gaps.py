#!/usr/bin/env python3
"""Coverage-gap report (read-only on the Hub): place list vs world_municipal_law, world_national_law and
american_municipal_law. Inputs are prepared by the helper steps documented in coverage_gaps.md
(/tmp/wl/cov: places.parquet downloads, AML tree + parquet footers, local out/ scan, QLever country table)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import collections, csv, json, re, sys
from pathlib import Path
import pyarrow.parquet as pq

W = Path("/tmp/wl/cov")
OUTDIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/state"))
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
ADD = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/codes/place_additions.csv"))


def uq(s):
    s = s.strip()
    m = re.match(r'^"(.*)"(?:@[\w-]+|\^\^<[^>]+>)?$', s)
    return m.group(1) if m else s.rsplit("/", 1)[-1].rstrip(">")


# ---- place list
places = {}
for fn, src in ((CAND, "candidate"), (ADD, "additions")):
    with fn.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = r["place_id"].strip()
            if pid and pid not in places:
                try:
                    pop = float(r.get("population") or 0)
                except ValueError:
                    pop = 0
                places[pid] = {"cc": r["country_code"] or "--", "level": r["admin_level"], "pop": pop, "src": src,
                               "name": r.get("place_name") or r.get("name")}
# ---- Hub
muni = pq.read_table(W / "world_municipal_law/world_law/places.parquet").to_pylist()
nat = pq.read_table(W / "world_national_law/world_law/places.parquet").to_pylist()
hub = {}
for r in muni + nat:
    hub[r["place_id"]] = {"cc": r["country_code"], "docs": r["total_docs"] or 0, "repo": "national" if r["place_id"].startswith("iso:") else "municipal"}
aml = json.load(open(W / "aml_rows.json"))
aml_by = collections.defaultdict(dict)
bad_footers = 0
for p, n, names in aml:
    m = re.search(r"(\d+)_html\.parquet$", p)
    if n is None:
        bad_footers += 1
        continue
    aml_by["gnis:" + m.group(1)][p] = n
aml_docs = {g: max(d.values()) for g, d in aml_by.items()}  # data/ data_2/ data_3/ copies: max, not sum
for g, n in aml_docs.items():
    h = hub.setdefault(g, {"cc": "US", "docs": 0, "repo": "american"})
    if h["repo"] != "american":
        h["repo"] += "+american"
    h["docs"] = max(h["docs"], n)
# ---- local cross-check (rows + metadata-only rows per place)
local = {}
for tree, cc, key, pid, rows, meta_only, files in json.load(open(W / "local_scan.json")):
    if pid:
        e = local.setdefault(pid, [0, 0])
        e[0] += rows
        e[1] += meta_only
# ---- countries
cinfo = {}
for line in open(W / "countries.tsv", encoding="utf-8").read().splitlines()[1:]:
    c = (line.split("\t") + [""] * 5)[:5]
    iso = uq(c[1])
    pop = float(uq(c[3]) or 0) if c[3] else 0
    if iso not in cinfo or pop > cinfo[iso]["pop"]:
        cinfo[iso] = {"name": uq(c[2]), "pop": pop, "un": bool(c[4].strip())}
# ---- per country
C = collections.defaultdict(lambda: collections.Counter())
for pid, p in places.items():
    c = C[p["cc"]]
    c["places"] += 1
    c["list_pop"] += p["pop"]
    h = hub.get(pid)
    if h and h["docs"] > 0:
        c["covered"] += 1
        c["docs"] += h["docs"]
        lo = local.get(pid)
        if lo and lo[0] and lo[1] == lo[0]:
            c["covered_metadata_only"] += 1
    else:
        c["uncovered"] += 1
        c["uncovered_pop"] += p["pop"]
    if h and h["repo"].endswith("american"):
        c["covered_via_american"] += 1 if h["docs"] else 0
hub_not_in_list = collections.Counter(h["cc"] for pid, h in hub.items() if pid not in places and not pid.startswith("iso:"))
national = {pid[4:]: h["docs"] for pid, h in hub.items() if pid.startswith("iso:") and "-" not in pid[4:]}
adm1 = collections.Counter(pid[4:].split("-")[0] for pid, h in hub.items() if pid.startswith("iso:") and "-" in pid[4:])
adm1_docs = collections.Counter()
for pid, h in hub.items():
    if pid.startswith("iso:") and "-" in pid:
        adm1_docs[pid[4:].split("-")[0]] += h["docs"]
# local vs hub mismatch
mism = [(pid, h["docs"], local[pid][0]) for pid, h in hub.items() if pid in local and h["repo"] in ("municipal", "national") and local[pid][0] != h["docs"]]
hub_only = [pid for pid, h in hub.items() if h["repo"] in ("municipal", "national") and pid not in local]
codes = sorted(set(C) | set(national) | set(adm1))
rows = []
for cc in codes:
    c = C.get(cc, collections.Counter())
    ci = cinfo.get(cc, {})
    rows.append({"country_code": cc, "country": ci.get("name", ""), "un_member": ci.get("un", False),
                 "country_population": int(ci.get("pop", 0)), "places_in_list": c["places"],
                 "places_with_docs": c["covered"], "pct_covered": round(100 * c["covered"] / c["places"], 2) if c["places"] else "",
                 "docs": c["docs"], "uncovered_places": c["uncovered"], "uncovered_population": int(c["uncovered_pop"]),
                 "list_population": int(c["list_pop"]), "covered_metadata_only": c["covered_metadata_only"],
                 "hub_places_not_in_list": hub_not_in_list.get(cc, 0),
                 "national_law": cc in national, "national_docs": national.get(cc, 0),
                 "adm1_regions_covered": adm1.get(cc, 0), "adm1_docs": adm1_docs.get(cc, 0)})
OUTDIR.mkdir(parents=True, exist_ok=True)
with (OUTDIR / "coverage_gaps.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
inlist = [r for r in rows if r["places_in_list"]]
tot = {k: sum(r[k] for r in inlist) for k in ("places_in_list", "places_with_docs", "docs", "uncovered_places", "covered_metadata_only")}
top_pop = sorted(inlist, key=lambda r: -r["uncovered_population"])[:30]
top_cnt = sorted(inlist, key=lambda r: -r["uncovered_places"])[:30]
no_nat = [r for r in rows if r["places_in_list"] and not r["national_law"]]
un_missing = sorted((cc, v["name"]) for cc, v in cinfo.items() if v["un"] and cc not in C)
un_no_nat = sorted((cc, v["name"]) for cc, v in cinfo.items() if v["un"] and cc not in national)
summary = {"totals": tot, "pct": round(100 * tot["places_with_docs"] / tot["places_in_list"], 2), "countries_in_list": len(inlist),
           "countries_with_any_coverage": sum(1 for r in inlist if r["places_with_docs"]), "national_countries": len(national),
           "adm1_regions": sum(adm1.values()), "hub_places_not_in_list": sum(hub_not_in_list.values()),
           "aml_gnis": len(aml_docs), "aml_footer_errors": bad_footers, "local_hub_doc_mismatch": len(mism),
           "hub_places_missing_locally": len(hub_only), "un_members_missing_from_list": un_missing,
           "un_members_without_national_law": len(un_no_nat)}
json.dump(summary, open(OUTDIR / "coverage_gaps_summary.json", "w"), indent=1, ensure_ascii=False)


def tbl(rs, cols):
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rs:
        out.append("| " + " | ".join(f"{r[c]:,}" if isinstance(r[c], int) and not isinstance(r[c], bool) else str(r[c]) for c in cols) + " |")
    return "\n".join(out)


md = [f"# Coverage gaps: place list vs Hub datasets\n",
      f"Generated by `pipeline/tools/coverage_gaps.py` (read-only on the Hub). Full per-country table: `coverage_gaps.csv`.\n",
      "## Top line",
      f"* Place list: **{tot['places_in_list']:,}** places in {len(inlist)} countries (candidate CSV + `codes/place_additions.csv`).",
      f"* Places with >= 1 doc on the Hub: **{tot['places_with_docs']:,} ({summary['pct']}%)**, {tot['docs']:,} docs; "
      f"{summary['countries_with_any_coverage']} countries have any covered place.",
      f"* Of these, {tot['covered_metadata_only']:,} have only metadata-only rows (`content_complete = false`, local out/ scan).",
      f"* National law (iso_<CC> in world_national_law): {len(national)} countries; adm1 regions: {sum(adm1.values())}.",
      f"* Hub places not in the list (excluded from %): {summary['hub_places_not_in_list']:,}.",
      f"* american_municipal_law: {len(aml_docs):,} GNIS places with an html parquet ({bad_footers} footers unreadable).",
      f"* Cross-check: {len(mism)} places where Hub total_docs differs from local out/ rows (runs in progress); {len(hub_only)} Hub places with no local file.\n",
      "## 30 largest uncovered countries by population (sum of uncovered places' population from the candidate CSV)",
      tbl(top_pop, ["country_code", "country", "country_population", "places_in_list", "places_with_docs", "pct_covered", "uncovered_places", "uncovered_population", "national_law"]),
      "\n## 30 largest by uncovered place count",
      tbl(top_cnt, ["country_code", "country", "places_in_list", "places_with_docs", "pct_covered", "uncovered_places", "docs", "national_law", "adm1_regions_covered"]),
      "\n## Countries with no national law (no iso_<CC> in world_national_law)",
      f"In the list ({len(no_nat)}): " + ", ".join(f"{r['country_code']} {r['country']}".strip() for r in no_nat),
      f"\nUN member states missing from the list entirely ({len(un_missing)}): " + (", ".join(f"{c} {n}" for c, n in un_missing) or "none"),
      f"\nUN member states without national law: {len(un_no_nat)} of 193.",
      ]
(OUTDIR / "coverage_gaps.md").write_text("\n".join(md) + "\n")
print(json.dumps(summary, ensure_ascii=False)[:1500])

CAVEATS = """
## Methodology
* **List** = `global_municipalities_candidate.csv` + `codes/place_additions.csv`, deduplicated by `place_id`.
  `codes/place_successors.csv` is not counted (old places are mapped to their successors).
* **Hub** = `world_law/places.parquet` of world_municipal_law and world_national_law (`total_docs` per place),
  plus american_municipal_law, where every `*_html.parquet` under `american_law/data/`, `data_2/`, `data_3/` and the
  repo root gives a GNIS. Its row count comes from the parquet footer, read through HfFileSystem at a pinned revision.
  A GNIS in several dirs counts with its **max** row count, not the sum. US places in the list are `gnis:<N>` and match directly.
* A place is **covered** when it has at least 1 doc on the Hub. Hub places that are not in the list are excluded from %.
* **National law** = `iso:<CC>` in world_national_law. **adm1 regions** = number of `iso:<CC>-<sub>` places there.
* **Cross-check**: every world_* Hub place was compared with the local out/ and out_national/ parquet rows (0
  differences, 0 Hub places missing locally at run time).
* Country population and UN membership come from Wikidata via QLever: P1082 (preferred rank) and P463 = Q1065
  without an end date.

## Caveats
* **Population sums double-count nested places.** The candidate list mixes levels (e.g. CN prefecture-level cities and
  their counties, IN districts and towns), so the uncovered population can exceed the country population. Use it
  only to rank countries. About 31% of list places have no population, and they count as 0.
* **Metadata-only places count as covered.** A place whose rows are all `content_complete = false` (title, number and
  date, no text) counts as covered. There are 4,066 such places, flagged per country in `covered_metadata_only`.
  Held rows are not on the Hub and don't count.
* **US**: the GNIS mapping is only as good as american_municipal_law's GNIS keys. Places it publishes under a GNIS
  that the candidate list doesn't have (e.g. a township vs a city GNIS) appear as uncovered and in "Hub places not
  in the list". There is no iso_US national law yet.
* The Hub data are a snapshot. Hourly runs add places, so a re-run will show higher numbers.
* "Countries with no national law" only means nothing is in world_national_law yet. Other lanes may have it staged.
* Paths: this report is written to `/workspace/world_law/pipeline/state/` as requested. The pipeline's own state dir
  is `/workspace/world_law/state/`, where run_loop's lock, ledger and runs.jsonl live.
"""
with (OUTDIR / "coverage_gaps.md").open("a") as f:
    f.write(CAVEATS)
