# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import importlib.util, json, random, re, time, collections, sys
import pyarrow.parquet as pq, requests, urllib.robotparser
spec = importlib.util.spec_from_file_location("hrx", "/workspace/scripts/hr_extract_articles.py")
hrx = importlib.util.module_from_spec(spec); spec.loader.exec_module(hrx)
hrx.FETCH_SLEEP = 1.5
ART = pq.read_table("{_CORPORA}/hr/extract/articles_merged.parquet", columns=["law_id", "article_number", "metadata_json"])
per = collections.defaultdict(list); kind = {}
for lid, num, md in zip(*[ART.column(c).to_pylist() for c in ["law_id", "article_number", "metadata_json"]]):
    if '"hr_split_hub_text"' in md:
        per[lid].append(num); kind.setdefault(lid, json.loads(md)["unit"])
random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 20260925)
byyear = collections.defaultdict(list)
for lid in per:
    y = re.match(r"hr-(\d{4})", lid).group(1); byyear[y].append(lid)
FORCE = sys.argv[2].split(",") if len(sys.argv) > 2 else []
pick = list(FORCE)
years = sorted(byyear)
while len(pick) < 20 + len(FORCE):
    for y in years:
        if len(pick) >= 20 + len(FORCE): break
        cands = [l for l in byyear[y] if l not in pick and l not in FORCE and (kind[l] == "clanak" or len(pick) % 4 == 3)]
        if cands: pick.append(random.choice(cands))
rp = urllib.robotparser.RobotFileParser(); rp.parse(requests.get(hrx.BASE + "/robots.txt", headers={"User-Agent": hrx.UA}, timeout=60).text.splitlines())
s = requests.Session(); s.headers.update({"User-Agent": hrx.UA})
res = []
for lid in pick:
    url, k = hrx.map_law(lid)
    h, final, outcome, code = hrx.fetch_html(s, rp, url)
    if outcome != "ok":
        res.append({"law_id": lid, "result": "fetch_" + outcome}); continue
    L = hrx.html_to_lines(h)
    units, lk = hrx.split_units(L)
    live_nums = [u["num"] for u in units]
    # independent: greedy sequential scan of all 'Članak N.' lines (quote-agnostic): take 1,2,3,... in order
    indep = []; want = 1
    for ln in L:
        m = re.match(r"^Član(?:ak)?\.?\s+(\d+)\s*\.?$", ln)
        if m and int(m.group(1)) == want:
            indep.append(str(want)); want += 1
    split_plain = [n for n in per[lid] if n.isdigit()]
    ok = live_nums == per[lid] and lk == kind[lid] and (lk != "clanak" or indep == split_plain)
    res.append({"law_id": lid, "unit": kind[lid], "split_n": len(per[lid]), "live_n": len(live_nums),
                "indep_seq_n": len(indep), "result": "pass" if ok else "mismatch",
                "split_nums": per[lid][:60] if not ok else None, "live_nums": live_nums[:60] if not ok else None})
    print(json.dumps(res[-1], ensure_ascii=False), flush=True)
out = {"checked": len(res), "pass": sum(r["result"] == "pass" for r in res),
       "mismatch": sum(r["result"] == "mismatch" for r in res), "fetch_other": sum(r["result"].startswith("fetch") for r in res), "rows": res}
json.dump(out, open("/workspace/country-law-triage/croatia_split_spotcheck.json" if len(sys.argv) < 4 else sys.argv[3], "w"), ensure_ascii=False, indent=1)
print("SUMMARY", out["checked"], out["pass"], out["mismatch"], out["fetch_other"])
