"""Offline (0 HTTP requests) pre-filter for sweep_hub.py. For every Hub data parquet, decide from local snapshots whether it can
contain no-text rows:  skip only when (a) the local place metadata (state/restore_*/world_law/metadata, = the Hub metadata json)
says doc_stats.content_incomplete == 0, and (b) the file's current Hub sha256 equals a sha256 recorded together with that
metadata (snapshot manifests or state/confirmed_batches), i.e. the file has not changed since the snapshot.
Writes sweep_work/hub_skip.jsonl {repo,path,sha,reason}."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import glob, json, sys
from collections import Counter
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr"))
import sweep_common as S
W = S.WL / "state"; MUNI, NAT = "endomorphosis/world_municipal_law", "endomorphosis/world_national_law"
SNAP_AT = "2026-10-17T04:58:00Z"   # restore_muni_git / restore_*_20261016 written 2026-10-16 21:58 PT
SNAP = [("restore_muni_git", MUNI), ("restore_muni_20261016", MUNI), ("restore_nat_20261016", NAT)]

def build():
    shas = {}
    for d, repo in SNAP:
        for f in glob.glob(f"{W}/{d}/world_law/manifests/*.jsonl"):
            for l in open(f):
                try: r = json.loads(l)
                except ValueError: continue
                p = r.get("path_in_repo", "")
                if p.endswith(".parquet") and r.get("sha256"): shas.setdefault((r.get("repo") or repo, p), set()).add(r["sha256"])
    for f in glob.glob(f"{W}/confirmed_batches/*.jsonl"):
        for l in open(f):
            try: r = json.loads(l)
            except ValueError: continue
            for h in r.get("hub_files") or []: shas.setdefault((r.get("hub_repo"), h["path"]), set()).add(h["sha256"])
    for l in open(W / "evicted_out.jsonl"):                   # out/ parquets evicted after their Hub upload was verified
        try: r = json.loads(l)
        except ValueError: continue
        if r.get("sha256"): shas.setdefault((r.get("repo"), r["rel"]), set()).add(r["sha256"])
    try:
        for k, v in json.load(open(W / "prune_out_sha_cache.json")).items():
            for root, repo in (((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/"), MUNI), ((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out_national/"), NAT)):
                if k.startswith(root): shas.setdefault((repo, k[len(root):]), set()).add(v[2])
    except (OSError, ValueError): pass
    for l in open(W / "bucket_migration.jsonl"):              # path moves (same LFS object): carry the shas over
        try: r = json.loads(l)
        except ValueError: continue
        if r.get("kind") == "data" and (r["repo"], r["old"]) in shas:
            shas.setdefault((r["repo"], r["new"]), set()).update(shas[(r["repo"], r["old"])])
    recent = set()                                            # re-uploaded after the metadata snapshot -> metadata is stale
    for f in glob.glob(f"{W}/confirmed_batches/*.jsonl"):
        for l in open(f):
            try: r = json.loads(l)
            except ValueError: continue
            if (r.get("confirmed_at") or "") >= SNAP_AT:
                for h in r.get("hub_files") or []: recent.add((r.get("hub_repo"), h["path"]))
    meta = {}
    for d, repo in SNAP:
        for f in glob.glob(f"{W}/{d}/world_law/metadata/**/*.json", recursive=True):
            try: m = json.load(open(f))
            except ValueError: continue
            for h in m.get("html_files") or []: meta.setdefault((repo, h), m)
    out, c, b = [], Counter(), Counter()
    for repo, fn in [(MUNI, "tree_world_municipal_law.jsonl"), (NAT, "tree_world_national_law.jsonl")]:
        for l in open(S.WORK / fn):
            e = json.loads(l); m = meta.get((repo, e["path"]))
            ci = ((m or {}).get("doc_stats") or {}).get("content_incomplete")
            same = e["sha"] in shas.get((repo, e["path"]), ()) and (repo, e["path"]) not in recent
            k = ("nometa" if m is None else "ci0" if ci == 0 else "ci>0") + ("|same" if same else "|changed")
            c[k] += 1; b[k] += e["size"]
            if k == "ci0|same": out.append({"repo": repo, "path": e["path"], "sha": e["sha"], "reason": "metadata content_incomplete=0, sha unchanged"})
    with open(S.WORK / "hub_skip.jsonl", "w") as w:
        for o in out: w.write(json.dumps(o) + "\n")
    return c, b

if __name__ == "__main__":
    c, b = build()
    for k in sorted(c): print(k, c[k], f"{b[k]/1e9:.2f} GB")
