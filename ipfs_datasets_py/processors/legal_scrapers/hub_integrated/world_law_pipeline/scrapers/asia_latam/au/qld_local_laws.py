#!/usr/bin/env python3
"""Australia / Queensland: council local laws + subordinate local laws from each council's official website.
(The state Local Laws Database at dlgwv.qld.gov.au sits behind a Cloudflare JS challenge and the data.qld.gov.au CSV
(2017) behind an AWS WAF challenge -> not usable without a browser challenge; logged.)
Places: QLD LGAs = Wikidata items with P131=Queensland (Q36074) that are in the candidate list; site = P856."""
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

TOPIC = re.compile(r"laws[\s\-_]*and[\s\-_]*regulations|laws-and-permits|laws[\s\-_]*(and[\s\-_]*)?policies|governance|council[\s\-_]*documents|publications", re.I)
STRONG = re.compile(r"local[\s\-_]*laws?", re.I)
DOC = re.compile(r"(subordinate\s+)?local\s*law|\bSLL\b|\bLL\s*\d", re.I)
EXCL = re.compile(r"proposed|draft|consultation|submission|agenda|minutes|public notice|gazette notice|form\b|application", re.I)
SEEDS = ["/local-laws", "/council/local-laws", "/your-council/local-laws", "/council/laws-and-policies/local-laws",
         "/about-council/local-laws", "/council/local-laws-and-policies", "/council/governance/local-laws"]


def places():
    cand = {r["qid"]: r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))) if r["country_code"] == "AU"}
    out = {}
    for r in csv.DictReader(open(HERE / "wd_qld.csv")):
        q = r["x"].rsplit("/", 1)[1]
        if q in cand and cand[q]["admin_level"] == "municipality" and q not in out:
            out[q] = {"qid": q, "place_id": cand[q]["place_id"], "name": cand[q]["place_name"] or r["xLabel"],
                      "site": r["site"] or cand[q]["source_url"] or None, "iso_3166_2": "AU-QLD"}
    return list(out.values())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--only", default="")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--retry-failed", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    c = CouncilCrawler("au_qld_ll", "AU", TOPIC, DOC, EXCL, SEEDS, platform="au_council_site", strong_re=STRONG)
    P = places()
    if a.only:
        P = [p for p in P if p["qid"] in a.only.split(",") or a.only.lower() in p["name"].lower()]
    logging.info("QLD councils: %d (with site %d)", len(P), sum(1 for p in P if p["site"]))
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(lambda p: c.run_place(p, a), P))
    logging.info("finished: %s", {s: sum(1 for r in res if r.get("status") == s) for s in ("done", "blocked", "no_site", "error")})
