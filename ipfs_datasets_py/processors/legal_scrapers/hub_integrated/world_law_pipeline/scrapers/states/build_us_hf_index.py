"""Build staging/states/_state/us_hf_index.sqlite: what justicedao/ipfs_state_laws (+ _normalized_graphrag) already hold,
for the states lane's old-repo skip (oldskip.py). READ-ONLY on the Hub data (local copies in /workspace/hfchk/dl);
does NOT touch the shared state/dedup/old_urls.sqlite (other lanes unaffected).
Tables:
  url(norm PRIMARY KEY, repo, place, n, frag)        dedup_index.norm_url(official_source_url); n = HF rows sharing it, frag = had '#'
  placerows(place, n)                                 HF rows per state (both repos, so counted twice where duplicated)
  cite(place, key, repo, n, n_good, PRIMARY KEY(place,key))
      key = 'sec:<section>'            section citation, lower-case, '.'/'§'/spaces -> '-', leading zeros dropped per part
            'ch:<chapter>'             chapter (or code abbrev) with n sections / n_good (text >= 200 chars, not a banner)
Built 2026-10-25 for Benjamin's HF-coverage check. Rebuild: python build_us_hf_index.py /workspace/hfchk"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, re, glob, json, sqlite3, os, collections
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline"))
import dedup_index as DX
import pyarrow.parquet as pq
ROOT = sys.argv[1] if len(sys.argv) > 1 else "/workspace/hfchk"
OUT = (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/states/_state/us_hf_index.sqlite")
BAN = re.compile(r"(cookie|javascript|access denied|page not found|cloudflare|captcha)", re.I)

def nsec(s):
    s = (s or "").strip().lower().replace("§", "").strip()
    s = re.sub(r"[\s.:_]+", "-", s).strip("-")
    return "-".join(p.lstrip("0") or "0" for p in s.split("-")) if s else ""

tmp = OUT + ".tmp"
if os.path.exists(tmp): os.unlink(tmp)
con = sqlite3.connect(tmp)
con.execute("CREATE TABLE url(norm TEXT PRIMARY KEY, repo TEXT, place TEXT, n INT, frag INT) WITHOUT ROWID")
con.execute("CREATE TABLE placerows(place TEXT PRIMARY KEY, n INT)")
U = {}; PR = collections.Counter()
con.execute("CREATE TABLE cite(place TEXT, key TEXT, repo TEXT, n INT, n_good INT, PRIMARY KEY(place,key)) WITHOUT ROWID")
ch = collections.defaultdict(lambda: [0, 0, None]); sec = {}
for repo in ("ipfs_state_laws", "ipfs_state_laws_normalized_graphrag"):
    for f in sorted(glob.glob(f"{ROOT}/dl/{repo}/data/corpus/part-*.parquet")):
        pf = pq.ParquetFile(f); RJ = "record_json" in pf.schema_arrow.names
        cols = ["record_json"] if RJ else ["jurisdiction_code", "text", "hierarchy", "official_source_url", "status"]
        for b in pf.iter_batches(batch_size=2048, columns=cols):
            for r in b.to_pylist():
                if RJ:
                    r = json.loads(r["record_json"]); h = r.get("hierarchy")
                    if isinstance(h, str):
                        try: import ast; r["hierarchy"] = ast.literal_eval(h)
                        except Exception: r["hierarchy"] = {}
                if (r.get("status") or "current") != "current": continue
                place = "US-" + (r.get("jurisdiction_code") or "?"); h = r.get("hierarchy") or {}; t = r.get("text") or ""
                good = len(t) >= 200 and not (len(t) < 600 and BAN.search(t[:300]))
                rp = "justicedao/" + repo
                n = DX.norm_url(r.get("official_source_url") if r.get("official_source_url") not in (None, "None") else None)
                PR[place] += 1
                if n and good:
                    u0 = U.get(n)
                    if u0: u0[2] += 1
                    else: U[n] = [rp, place, 1, int("#" in (r.get("official_source_url") or ""))]
                s = nsec(h.get("section"))
                if s and good: sec[(place, "sec:" + s)] = rp
                c = nsec(h.get("chapter") or h.get("title"))
                if c:
                    k = (place, "ch:" + c); ch[k][0] += 1; ch[k][1] += good; ch[k][2] = rp
con.executemany("INSERT INTO url VALUES(?,?,?,?,?)", [(k, *v) for k, v in U.items()]); del U
con.executemany("INSERT OR REPLACE INTO placerows VALUES(?,?)", list(PR.items()))
con.executemany("INSERT OR IGNORE INTO cite VALUES(?,?,?,?,?)", [(p, k, r, 1, 1) for (p, k), r in sec.items()])
con.executemany("INSERT OR REPLACE INTO cite VALUES(?,?,?,?,?)", [(p, k, v[2], v[0], v[1]) for (p, k), v in ch.items()])
con.commit()
print("urls", con.execute("select count(*) from url").fetchone()[0], "cites", con.execute("select count(*) from cite").fetchone()[0])
con.close(); os.replace(tmp, OUT)
