#!/usr/bin/env python3
"""Lane-wide staging summary (docs/places per country & source, unmatched) -> staging/asia_latam/_status_all.json"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys as _sys; _sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/common")); from jsonl_io import open_text, glob_jsonl, locate  # noqa: E402,E702
import json, glob, os, re, collections, csv
from pathlib import Path
ST = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
PR = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/processed/asia_latam"))
out = {}
DOCID = re.compile(r'"doc_id":\s*"([^"]+)"')
LEDGER = ST / "_state" / "status_ledger"   # per-file doc counts, so files pruned from processed/ still count (cumulative)
LEDGER.mkdir(parents=True, exist_ok=True)


def _mtime(f):
    try:
        return os.path.getmtime(f)
    except FileNotFoundError:   # pruned/gzipped mid-scan
        return None


for cc in ("JP", "ES", "PE", "BR", "CL", "MX", "AU", "ZA", "ID"):
    docs = collections.Counter(); places = collections.defaultdict(set); seen = set(); dup = 0; vanished = 0
    lp = LEDGER / f"{cc}.json"
    try:
        ledger = json.load(open(lp))   # canonical basename (no .gz) -> {pk, src, n, mtime, full}
    except (FileNotFoundError, ValueError):
        ledger = {}
    # staged files + files the uploader already moved to processed/ (possibly gzipped by common/gzip_processed.py)
    files = glob_jsonl(str(ST / cc / "*.jsonl")) + glob_jsonl(str(PR / cc / "*.jsonl"))
    mt = {f: _mtime(f) for f in files}
    files = [f for f in files if mt[f] is not None]
    full_at = {}  # place_key -> mtime of its latest .full batch (a .full batch supersedes that place's earlier batches)
    for f in files:
        if ".full" in os.path.basename(f):
            pk = os.path.basename(f).split(".")[0]; full_at[pk] = max(full_at.get(pk, 0), mt[f])
    for b, e in ledger.items():   # .full batches that were pruned still supersede
        if e.get("full"):
            full_at[e["pk"]] = max(full_at.get(e["pk"], 0), e["mtime"])
    live = set()
    for f in files:
        b = os.path.basename(f[:-3] if f.endswith(".gz") else f); pk = b.split(".")[0]
        if pk in full_at and ".full" not in b and mt[f] < full_at[pk]:
            live.add(b); continue
        m = re.search(r"\.(mx_municipal|ojp_puebla|archivepdf|archive|bocm|borm|caceres|gipuzkoa|cordoba|granada|leon|huesca|soria|avila|guadalajara|lugo|ourense|cadiz|castellon|gobpe|sapl|lexml|au_qld_ll|za_bylaws|full|jp\d+)", b)
        src = m.group(1) if m else "other"
        src = "jp_reiki" if src.startswith("jp") or src == "full" else src
        src = f"{cc}_{src}".lower() if src in ("archive", "archivepdf") else src  # web-archive backfill (arch/)
        n = 0; keys = []
        def _lines(f=f):
            try:
                yield from open_text(f)
            except FileNotFoundError:
                if f.endswith(".gz"):
                    raise
                yield from open_text(f + ".gz")   # gzip_processed swapped it to .gz mid-scan
        try:
            for line in _lines():
                mm = DOCID.search(line[:2000]) or DOCID.search(line)
                key = (pk, mm.group(1)) if mm else (f, n)
                if key in seen:
                    dup += 1; continue
                seen.add(key); keys.append(key); n += 1
        except FileNotFoundError:   # pruned between glob and open: fall back to the ledger entry below
            vanished += 1; seen.difference_update(keys); continue
        live.add(b)
        ledger[b] = {"pk": pk, "src": src, "n": n, "mtime": mt[f], "full": ".full" in b}
        docs[src] += n; places[src].add(pk); places["_all"].add(pk)
    # pruned = in ledger, no longer on disk (Normalizer prunes processed/ after Hub commit). Counted from ledger.
    pr_docs = collections.Counter(); pr_n = 0
    for b, e in ledger.items():
        if b in live:
            continue
        if e["pk"] in full_at and not e.get("full") and e["mtime"] < full_at[e["pk"]]:
            continue
        pr_docs[e["src"]] += e["n"]; places[e["src"]].add(e["pk"]); places["_all"].add(e["pk"]); pr_n += 1
    t = lp.with_name("." + lp.name + ".tmp"); t.write_text(json.dumps(ledger)); os.replace(t, lp)
    cum = docs + pr_docs
    out[cc] = {"docs_by_source": dict(cum), "places_by_source": {k: len(v) for k, v in places.items() if k != "_all"},
               "docs": sum(cum.values()), "docs_on_disk": sum(docs.values()), "docs_pruned": sum(pr_docs.values()),
               "files_pruned": pr_n, "vanished_mid_scan": vanished,
               "places": len(places["_all"]), "duplicate_rows_skipped": dup}
unm = {}
for name in ("_unmatched_jp.csv", "_unmatched_es.csv", "_unmatched_es_bop.csv", "_unmatched_pe.csv", "_unmatched_br.csv",
             "_unmatched_id.csv"):
    p = ST / name
    unm[name] = sum(1 for _ in open(p)) if p.exists() else 0
out["unmatched_rows"] = unm
# still-unmatched staged rows = rows in _unmatched/<CC>/ minus doc_ids re-emitted by the reresolve scripts (manifests)
reem, reem_files = set(), set()
for mp in glob.glob(str(ST / "_unmatched" / "_reemitted_*.jsonl")):
    for line in open(mp, encoding="utf8"):
        mm = DOCID.search(line)
        if mm:
            reem.add(mm.group(1))
        else:  # file-level manifest rows (pe/reresolve.py): the whole unmatched file was re-emitted
            uf = json.loads(line).get("unmatched_file")
            if uf:
                reem_files.add(os.path.basename(uf))
still = {}
for d in sorted(glob.glob(str(ST / "_unmatched" / "*" ))):
    if os.path.isdir(d):
        c = t_ = 0
        for f in glob_jsonl(d + "/*.jsonl"):
            if os.path.basename(f) in reem_files:
                t_ += sum(1 for _ in open(f, encoding="utf8")); continue
            try:
                lines = list(open_text(f))
            except FileNotFoundError:
                continue
            for line in lines:
                mm = DOCID.search(line[:3000]) or DOCID.search(line); t_ += 1
                c += 0 if (mm and mm.group(1) in reem) else 1
        still[os.path.basename(d)] = {"parked_rows": t_, "still_unmatched": c}
out["unmatched_staged"] = still
aw = {}  # web-archive backfill jobs (arch/): per-job stats.json
for sp in sorted(glob.glob(str(ST / "_archive_work" / "*" / "stats.json"))):
    try:
        d = json.load(open(sp))
        aw[Path(sp).parent.name] = {k: d.get(k) for k in ("candidates", "staged_total", "done_total", "src_wayback", "src_commoncrawl",
                                                           "complete", "incomplete", "updated", "final")}
    except Exception:
        pass
out["archive_jobs"] = aw
out["lane_total"] = {"docs": sum(v["docs"] for k, v in out.items() if k not in ("unmatched_rows", "unmatched_staged", "archive_jobs")),
                     "docs_on_disk": sum(v["docs_on_disk"] for k, v in out.items() if k not in ("unmatched_rows", "unmatched_staged", "archive_jobs")),
                     "places": sum(v["places"] for k, v in out.items() if k not in ("unmatched_rows", "unmatched_staged", "archive_jobs"))}
t = ST / "._status_all.json.tmp"; t.write_text(json.dumps(out, indent=1, ensure_ascii=False)); os.replace(t, ST / "_status_all.json")
print(json.dumps(out, indent=1, ensure_ascii=False))
