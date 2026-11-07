"""2026-11-02 topup3 post-filter: keep only URLs on the county's own registrable domain (drops e.g. stmb.bayern.de forms,
form-solutions servlets), drop URLs/doc_ids already staged by OTHER lanes (~/.ipfs_datasets/world_law/staging/** outside counties,
list in /tmp/otherlanes.txt), drop Rottal-Inn Innkraftwerk planning-procedure annexes (technical plans, not acts)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, re, sys, hashlib, urllib.parse
from urllib.parse import urlsplit
other = set(re.findall(r'"[a-z_]+": ?"([^"]+)"', open("/tmp/otherlanes.txt").read()))
T = {e["qid"]: e for e in json.load(open("de_by_topup3_targets.json"))}
for q in sys.argv[1:]:
    p = f"entries/de_by_wd_{q}.json"; E = json.load(open(p)); e = T[q]
    dom = ".".join(urlsplit((e.get("index_urls") or [e.get("url")])[0]).netloc.split(".")[-2:])
    keep, drop = [], {"offdomain": 0, "otherlane": 0, "annex": 0}
    for it in E["items"]:
        u = it["url"]; h = urlsplit(u).netloc
        if not (h == dom or h.endswith("." + dom)): drop["offdomain"] += 1; continue
        did = "de_by_kreisrecht:" + hashlib.sha1(u.encode()).hexdigest()[:16]
        if u in other or urllib.parse.unquote(u) in other or did in other: drop["otherlane"] += 1; continue
        if q == "Q10477" and re.search(r"Weiterbetrieb_Innkraftwerk|_GER_", u): drop["annex"] += 1; continue
        keep.append(it)
    E["items"] = keep; json.dump(E, open(p, "w"), ensure_ascii=False)
    print(q, E["place_name"], "kept", len(keep), drop)
