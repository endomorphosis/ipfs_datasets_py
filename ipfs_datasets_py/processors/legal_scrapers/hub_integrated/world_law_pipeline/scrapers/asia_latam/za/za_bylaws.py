#!/usr/bin/env python3
"""South Africa: municipal by-laws from each municipality's official website (NOT Laws.Africa / openbylaws.org.za,
which is skipped per lane rules). Places: ZA municipalities in the candidate list (wd:Q...), site from the candidate
list or Wikidata P856."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, csv, logging, re, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common")); sys.path.insert(0, str(HERE.parent))
from council_sites import CouncilCrawler  # noqa: E402

STRONG = re.compile(r"by[\s\-_]*laws?|bylaws?|verordening", re.I)
TOPIC = re.compile(r"legislation|policies|governance|documents|publications|resources|downloads|council", re.I)
DOC = re.compile(r"by[\s\-_]*laws?|bylaws?|verordening", re.I)
EXCL = re.compile(r"draft|proposed|comment|consultation|notice of|invitation|agenda|minutes|tender|vacanc|application form", re.I)
SEEDS = ["/by-laws", "/bylaws", "/documents/by-laws", "/council/by-laws", "/by-laws-2", "/legislation/by-laws",
         "/index.php/by-laws", "/documents/bylaws", "/governance/by-laws", "/resources/by-laws"]
SKIP_HOSTS = ("openbylaws.org.za", "laws.africa")


def places():
    cand = {r["qid"]: r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv")))
            if r["country_code"] == "ZA" and r["admin_level"] == "municipality"}
    wd = {}
    for r in csv.DictReader(open(HERE / "wd_za_sites.csv")):
        wd.setdefault(r["x"].rsplit("/", 1)[1], r["site"])
    out = []
    for q, r in cand.items():
        site = r["source_url"] or wd.get(q)
        if site and any(h in site for h in SKIP_HOSTS):
            site = wd.get(q) if wd.get(q) and not any(h in wd.get(q) for h in SKIP_HOSTS) else None
        out.append({"qid": q, "place_id": r["place_id"], "name": r["place_name"], "site": site or None, "iso_3166_2": r["iso_3166_2"] or None})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", default="")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--retry-failed", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = CouncilCrawler("za_bylaws", "ZA", TOPIC, DOC, EXCL, SEEDS, platform="za_municipal_site", strong_re=STRONG, max_pages=50)
    P = places()
    if a.only:
        P = [p for p in P if p["qid"] in a.only.split(",") or a.only.lower() in p["name"].lower()]
    logging.info("ZA municipalities: %d (with site %d)", len(P), sum(1 for p in P if p["site"]))
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda p: c.run_place(p, a), P))
    logging.info("finished: %s", {s: sum(1 for r in res if r.get("status") == s) for s in ("done", "blocked", "no_site", "error")})
