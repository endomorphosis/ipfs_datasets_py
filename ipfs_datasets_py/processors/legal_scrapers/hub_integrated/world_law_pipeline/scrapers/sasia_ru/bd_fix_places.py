"""2026-11-04: repair BD gazette places after (a) one-row `.full` batches wiped earlier docs per place and (b) district
misattribution. Reads every bdgazette row we staged (processed/ + staging/ BD) plus the published Hub BD parquets
(_bd/hub_bd), re-runs bd_gazette.match (with bd_rematch) on each title, fixes place_name from Wikidata English labels,
and writes per-place NON-full restore batches staging/sasia_ru/BD/wd_<QID>.fix_<ts>.jsonl (all docs for that place;
newer than every .full so they win). Writes _bd/misattributed_for_normalizer_v2.tsv. --write to stage."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys, os, re, json, glob, time, argparse, collections
from datetime import datetime, timezone
for k in ('http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','all_proxy'): os.environ.pop(k, None)
os.environ['ARCHIVE_LANE'] = 'sasia_ru'
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/pipeline/scrapers/sasia_ru"))
import pandas as pd, pyarrow as pa
pa.set_cpu_count(1); pa.set_io_thread_count(1)
HUB = pd.concat([pd.read_parquet(f) for f in glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)) + "/staging/sasia_ru/_bd/hub_bd/wd_*_html.parquet"))]).drop(columns=["html"])
import resource; _sr = resource.setrlimit; resource.setrlimit = lambda *a: None  # bd_gazette sets RLIMIT_AS 2GB, which pyarrow+csv trip over; RSS checked instead
import bd_gazette as g
resource.setrlimit = _sr
from schema import validate_record, validate_file, place_key
W = _wl_os.environ.get("WORLD_LAW_ROOT", str(_WORLD)); D = g.D
ap = argparse.ArgumentParser(); ap.add_argument("--write", action="store_true"); a = ap.parse_args()
P = g.load_places(); PL = {p["qid"]: p for p in P}
def batch_ts(f):
    m = re.search(r"(\d{8}T\d{6})Z", f); return m.group(1) if m else "0"
# 1) our staged rows, newest per doc_id
mine = {}
for f in sorted(glob.glob(f"{W}/processed/sasia_ru/BD/*.jsonl") + glob.glob(f"{W}/staging/sasia_ru/BD/*.jsonl")):
    if ".fix_" in f: continue
    for l in open(f):
        r = json.loads(l)
        if r.get("source_platform") != "bd_gazette": continue
        if r["doc_id"] not in mine or batch_ts(f) >= mine[r["doc_id"]][0]: mine[r["doc_id"]] = (batch_ts(f), r, f)
# 2) Hub
hub = HUB
hubg = hub[hub.source_platform == "bd_gazette"]
hub_by_place = hub.groupby("place_id").doc_id.apply(set).to_dict()
BN1 = {json.loads(l)["qid"]: (json.loads(l)["bn"] or [None])[0] for l in open(f"{D}/wd_bd_bn.jsonl")}
def pname(q):  # English label only if it carries a body-type word (Q3349044's en label is 'Rony'), else Bengali label
    e = en.get(q)
    if e and re.search(r"Upazila|Upazilla|Municipality|Pourashava|Paurashava|Pourashava|District|Union|City Corporation|Thana|Sadar", str(e or "")): return e
    return BN1.get(q) or e or PL[q]["name"]
# 4) re-match everything
def newq(title):
    m = g.match(title, P); return next(iter(m)) if len(m) == 1 and "AMBIG" not in m else ""
audit = []; out = collections.defaultdict(dict); stat = collections.Counter()
hub_rows = {r.doc_id: r for r in hubg.itertuples()}
alldocs = set(mine) | set(hub_rows)
for did in sorted(alldocs):
    if did in mine: _, r, src = mine[did]; r = dict(r)
    else:
        h = hub_rows[did]._asdict(); h.pop("Index", None)
        r = {k: (None if (isinstance(v, float) and v != v) else v) for k, v in h.items() if k not in ("cid", "doc_order", "html", "html_title", "gnis")}
        em = json.loads(r["extra_metadata"]) if isinstance(r.get("extra_metadata"), str) else (r.get("extra_metadata") or {})
        r["extra_metadata"] = em; q0 = r["place_id"][3:]
        r.update({"qid": q0, "admin_level": PL.get(q0, {}).get("level"), "platform": "bd_gazette", "platform_place_id": did.split(":")[1]}); src = "hub"
        if em.get("file_url"): r["file_url"] = em.pop("file_url")
        for k in [k for k, v in list(r.items()) if v is None]: r.pop(k)
    old = r["place_id"][3:]; published_at = None
    for p_, ds in hub_by_place.items():
        if did in ds: published_at = p_[3:]
    nq = newq(r.get("title_native") or "")
    if isinstance(r.get("extra_metadata"), dict) and r["extra_metadata"].get("place_rematch"): nq = nq or old
    status = "ok" if nq == old else ("reassign" if nq else "unmatched")
    stat[status] += 1; stat["published"] += bool(published_at)
    audit.append((did, published_at or "", old, PL.get(old, {}).get("name"), nq, nq, status, src.split("/")[-1], (r.get("title_native") or "")[:200]))
    if status == "unmatched": continue
    em = dict(r.get("extra_metadata") or {})
    if status == "reassign": em["place_rematch"] = {"old_qid": old, "method": "bd_rematch_20261104"}
    r.update({"place_id": "wd:" + nq, "qid": nq, "admin_level": PL[nq]["level"], "place_name": None, "extra_metadata": em})
    out[nq][did] = r
USED = set(out)
# 3) English labels
en = {}
cache = f"{D}/wd_bd_en.jsonl"
if os.path.exists(cache): en = {json.loads(l)["qid"]: json.loads(l)["en"] for l in open(cache)}
need = sorted({q for q in USED if q and q not in en})
with open(cache, "a") as fo:
    for i in range(0, len(need), 50):
        import requests
        for t in range(8):
            j = requests.get("https://www.wikidata.org/w/api.php", params=dict(action="wbgetentities", ids="|".join(need[i:i+50]), props="labels", languages="en", format="json"), headers={"User-Agent": g.UA}, timeout=60).json()
            if "error" not in j: break
            time.sleep(10)
        for q, e in j.get("entities", {}).items():
            en[q] = e.get("labels", {}).get("en", {}).get("value"); fo.write(json.dumps({"qid": q, "en": en[q]}, ensure_ascii=False) + "\n")
for q, docs in out.items():
    for r in docs.values(): r["place_name"] = pname(q)
audit = [t[:5] + ((pname(t[5]) if t[5] else ""),) + t[6:] for t in audit]
with open(f"{D}/misattributed_for_normalizer_v2.tsv", "w") as f:
    f.write("doc_id\tpublished_place\tstaged_or_hub_qid\told_place_name\tcorrect_qid\tcorrect_place_name\tstatus\tsource\ttitle\n")
    for t in audit: f.write("\t".join(str(x) for x in t) + "\n")
print(json.dumps(stat))
# safe to quarantine: published wrong rows whose published place still has other docs after the fix
safe = []
for t in audit:
    did, pub, old, _, nq, _, st = t[:7]
    if pub and st != "ok":
        others = (hub_by_place.get("wd:" + pub, set()) - {did}) | set(out.get(pub, {}))
        safe.append((did, pub, st, len(others - {did})))
print("published_wrong", [(s[0], s[1], s[2], "safe" if s[3] else "NOT safe (place would be empty)") for s in safe])
print("places", len(out), "docs", sum(len(v) for v in out.values()))
if a.write:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); ok = bad = 0
    for q, docs in sorted(out.items()):
        recs = list(docs.values())
        errs = [e for r in recs for e in (validate_record(r) or [])]
        if errs: print("INVALID", q, errs[:3]); bad += 1; continue
        fn = f"{W}/staging/sasia_ru/BD/{place_key('wd:' + q)}.fix_{ts}.jsonl"; tmp = f"{D}/fix/{os.path.basename(fn)}"
        with open(tmp, "w", encoding="utf-8") as fo:
            for r in recs: fo.write(json.dumps(r, ensure_ascii=False) + "\n")
        res = validate_file(tmp, expect_place_key=place_key("wd:" + q))
        if not res["ok"]: print("FILE INVALID", q, str(res)[:300]); bad += 1; continue
        os.rename(tmp, fn); ok += 1
    print(json.dumps({"fix_files": ok, "invalid": bad, "ts": ts}))
