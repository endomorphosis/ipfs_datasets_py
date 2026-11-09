#!/usr/bin/env python3
"""Verify batch-6 pack: schema/codec/row groups vs live, id uniqueness across live+new, orphans, article_count,
section gaps/dups, Jan-1 dates, title/maker sources, live files untouched, sha256s, secret scan (rg + parquet strings), YAML safe_load."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import glob, hashlib, json, os, re, subprocess, sys
from collections import Counter
from pathlib import Path
import pyarrow.parquet as pq, yaml
W = Path(os.environ.get("ZA_WORK", (str(_LEGAL_WS) + "/world_laws/za_metro"))); P = W / "hf_b6/ipfs_south_africa_municipal_laws"; T = W / "tip"
SEC = r"hf_[A-Za-z0-9]{20,}|token|secret|password|authorization|api[_-]?key|BEGIN .*PRIVATE"
WEBMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@(?:gmail|googlemail|yahoo|ymail|hotmail|outlook|live|msn|aol|icloud|gmx|protonmail|zoho|yandex|telkomsa|vodamail|mweb|iafrica|absamail)\.[A-Za-z.]{2,10}\b", re.I)
out, fail = {}, []
def ck(c, m):
    if not c: fail.append(m)
for name in ("laws", "articles"):
    live = pq.ParquetFile(T / f"data/{name}-00003.parquet"); new = pq.ParquetFile(P / f"data/{name}-00004.parquet")
    ck(new.schema_arrow.equals(live.schema_arrow), f"{name} schema mismatch")
    ck(new.metadata.num_row_groups == 1 and all(new.metadata.row_group(0).column(i).compression == "ZSTD" for i in range(new.metadata.num_columns)), f"{name} codec/rg")
    out[name] = {"rows": new.metadata.num_rows, "row_groups": new.metadata.num_row_groups, "codec": new.metadata.row_group(0).column(0).compression,
                 "sha256": hashlib.sha256((P / f"data/{name}-00004.parquet").read_bytes()).hexdigest()}
L = pq.read_table(P / "data/laws-00004.parquet").to_pandas(); A = pq.read_table(P / "data/articles-00004.parquet").to_pandas()
lid = set(); aid = set()
for f in glob.glob(str(T / "data/laws-*.parquet")): lid |= set(pq.read_table(f, columns=["id"]).column(0).to_pylist())
for f in glob.glob(str(T / "data/articles-*.parquet")): aid |= set(pq.read_table(f, columns=["id"]).column(0).to_pylist())
ck(not (set(L.id) & lid) and L.id.is_unique, "law id collision"); ck(not (set(A.id) & aid) and A.id.is_unique, "article id collision")
ck(set(A.law_id) <= set(L.id), "orphan articles"); ck((A.groupby("law_id").size().reindex(L.id).fillna(0).astype(int).values == L.article_count.values).all(), "article_count mismatch")
ck(not L.date.str.startswith("1 January").any(), "Jan-1 date present")
gaps = dups = 0; mk = Counter()
for m in L.metadata_json:
    d = json.loads(m); gaps += bool(d["section_split"]["gaps"]); dups += bool(d["section_split"]["duplicates"]); mk[d["maker_check"]["status"]] += 1
    ck(d["title_source"] == "masthead", "title source")
ck(L.municipality_id.isin(["za-cpt", "za-jhb"]).all(), "municipality")
# live files untouched: pack ships no live shard names
shipped = sorted(str(p.relative_to(P)) for p in P.rglob("*") if p.is_file())
live_names = {f"data/{n}" for n in os.listdir(T / "data")}
ck(not (set(shipped) & live_names), "pack overwrites a live data file")
ck(not (P / "README.md").exists(), "top-level README present")
rg = subprocess.run(["rg", "-n", "-i", SEC, str(P)], capture_output=True, text=True).stdout.strip().splitlines()
hits = []
for df in (L, A):
    for c in df.columns:
        if df[c].dtype == object:
            for v in df[c].dropna().astype(str):
                if re.search(r"hf_[A-Za-z0-9]{20,}|BEGIN .*PRIVATE|api[_-]?key\s*[:=]", v, re.I): hits.append((c, v[:80]))
                if WEBMAIL.search(v): hits.append((c, "webmail"))
ylm = []
for y in list(P.rglob("*.yml")) + list(P.rglob("*.yaml")): yaml.safe_load(open(y)); ylm.append(str(y))
for md in P.rglob("*.md"):
    t = md.read_text()
    if t.startswith("---"): yaml.safe_load(t.split("---")[1]); ylm.append(str(md))
ck(not hits, f"parquet secret/webmail hits {hits[:5]}")
# PII scan (batch-6 fix): every string column of both new shards; fail-level hits fail verify. Ids/offsets only.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pii_scan_za_metro import scan as pii_scan
pii = pii_scan([str(P / "data/laws-00004.parquet"), str(P / "data/articles-00004.parquet")])
pii_counts = dict(Counter(f"{h['level']}:{h['kind']}" for h in pii))
REVIEW = {"phone_landline": "reviewed: gazette printer / Government Printing Works contact footer (publisher, not personal)",
          "sa_id_13digit_other": "reviewed: not an ID number (digit run inside a value; no valid YYMMDD/Luhn)"}
(P / "manifests/batch6_pii_scan.json").write_text(json.dumps({"counts": pii_counts, "fail": sum(h["level"] == "fail" for h in pii),
    "warn": sum(h["level"] == "warn" for h in pii), "hits": [dict(h, review=REVIEW.get(h["kind"], "")) for h in pii],
    "note": "row id + column + character offset only; matched values are never written"}, indent=1) + "\n")
ck(not any(h["level"] == "fail" for h in pii), f"PII fail-level hits {pii_counts}")
# page-boundary filter must have run on every law
ck(all("page_boundary" in json.loads(m) for m in L.metadata_json), "page_boundary missing")
res = {"files": out, "laws": len(L), "articles": len(A), "by_city": L.municipality_id.value_counts().to_dict(), "laws_with_gaps": gaps, "laws_with_dups": dups,
       "maker": dict(mk), "rg_hits": rg, "parquet_hits": len(hits), "pii_counts": pii_counts, "yaml_safe_load": ylm, "shipped": shipped, "fail": fail}
(P / "manifests/batch6_verify.json").write_text(json.dumps({k: v for k, v in res.items() if k != "shipped"}, indent=1) + "\n")
print(json.dumps(res, indent=1)); sys.exit(1 if fail else 0)
