#!/usr/bin/env python3
"""Verify ZA provincial pack1: codec ZSTD + one row group; schema = national + 4 columns; unique ids; article FK; no Jan-1 / malformed dates;
README YAML safe_load; secret scan (pack files) + parquet string scan with webmail redaction check; PII scan (FAIL on valid SA ID numbers,
non-government emails, mobile numbers, names near street addresses, private gazette notices). Never prints matched values.
Writes manifests/batch1_pii_scan.json, batch1_secret_scan.json, batch1_verify.json, batch1_files.json (sha256 of every pack file)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_LEGAL_WS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_WORKSPACE", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_workspace")))
import hashlib, json, os, re, sys
from pathlib import Path
import pyarrow.parquet as pq, yaml
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pii_scan_za_prov import scan  # noqa
from stage_za_prov import WEBMAIL  # noqa
W = Path(os.environ.get("ZA_WORK", (str(_LEGAL_WS) + "/world_laws/za_prov"))); P = W / "hf_b1/ipfs_south_africa_provincial_laws"
fails, notes = [], {}
L, A = P / "data/laws.parquet", P / "data/articles.parquet"
for f in (L, A):
    m = pq.ParquetFile(f).metadata
    if m.num_row_groups != 1: fails.append(f"{f.name}: row_groups={m.num_row_groups}")
    cs = {m.row_group(0).column(i).compression for i in range(m.num_columns)} if m.num_row_groups else set()
    if cs != {"ZSTD"}: fails.append(f"{f.name}: codec {cs}")
nl = [x.name for x in pq.read_schema(W / "national/laws.parquet")] + ["province", "gazette_no", "gazette_date", "act_no"]
if pq.read_schema(L).names != nl: fails.append("laws schema mismatch")
if pq.read_schema(A).names != pq.read_schema(W / "national/articles.parquet").names: fails.append("articles schema mismatch")
lt = pq.read_table(L).to_pylist(); at = pq.read_table(A).to_pylist()
ids = [r["id"] for r in lt]; aids = [r["id"] for r in at]
if len(set(ids)) != len(ids): fails.append("dup law ids")
if len(set(aids)) != len(aids): fails.append("dup article ids")
if any(r["law_id"] not in set(ids) for r in at): fails.append("article FK")
for r in lt:
    for c in ("date", "date_issued", "gazette_date"):
        v = r[c]
        if v and (not re.fullmatch(r"(?:19|20)\d\d-\d\d-\d\d", v) or v.endswith("-01-01")): fails.append(f"{r['id']} bad {c}")
    if r["article_count"] != sum(1 for a in at if a["law_id"] == r["id"]): fails.append(f"{r['id']} article_count")
    if not r["title"] or re.search(r"\bBill\b", r["title"]): fails.append(f"{r['id']} title")
    if r["language"] != "en": fails.append(f"{r['id']} language")
    mj = json.loads(r["metadata_json"])
    if not mj.get("bounds"): fails.append(f"{r['id']} bounds_not_applied")
    if mj.get("maker_status") != "confirmed_enacting_clause" and not re.search(r"(?i)western cape|kwazulu", r["title"]): fails.append(f"{r['id']} maker")
    if not re.search(r"(?i)\bAct\b", r["title"]) or r["title"] != r["title"].strip(): fails.append(f"{r['id']} masthead_title")
    if not isinstance(mj.get("repeals_express"), list): fails.append(f"{r['id']} repeals_not_express_list")
    if r["province"] != "Western Cape": fails.append(f"{r['id']} province_not_in_pack1_scope")
notes["maker_confirmed"] = sum(1 for r in lt if json.loads(r["metadata_json"]).get("maker_status") == "confirmed_enacting_clause")
notes["laws"] = len(lt); notes["articles"] = len(at)
fm = (P / "README.md").read_text().split("---")[1]
try: y = yaml.safe_load(fm); notes["yaml_safe_load"] = "ok" if isinstance(y, dict) and y.get("configs") else "bad"
except Exception as e: y = None; notes["yaml_safe_load"] = f"error {type(e).__name__}"
if notes["yaml_safe_load"] != "ok": fails.append("yaml")
pii = scan([str(L), str(A)]); pf = [h for h in pii if h["level"] == "fail"]
json.dump({"files": ["data/laws.parquet", "data/articles.parquet"], "fail": len(pf), "warn": len(pii) - len(pf),
           "counts": {k: sum(1 for h in pii if f"{h['level']}:{h['kind']}" == k) for k in sorted({f"{h['level']}:{h['kind']}" for h in pii})},
           "hits": pii}, open(P / "manifests/batch1_pii_scan.json", "w"), indent=1)
if pf: fails.append(f"pii_fail={len(pf)}")
notes["pii"] = {"fail": len(pf), "warn": len(pii) - len(pf)}
SEC = re.compile(r"hf_[A-Za-z0-9]{30,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
                 r"xox[abpr]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{32,}|temp[a]uth=|[?&](?:token|access_token|sig|signature)=[A-Za-z0-9%._-]{16,}|Authorization:\s*Bearer", re.I)
sh = []
for f in sorted(P.rglob("*")):
    if f.is_file() and f.suffix != ".parquet" and f.name not in ("batch1_secret_scan.json", "batch1_pii_scan.json"):
        for m in SEC.finditer(f.read_text(errors="replace")): sh.append({"file": str(f.relative_to(P)), "offset": m.start(), "kind": "secret_pattern"})
wm = 0
for t, name in ((lt, "laws"), (at, "articles")):
    for r in t:
        for c, v in r.items():
            if isinstance(v, str):
                for m in SEC.finditer(v): sh.append({"file": f"data/{name}.parquet", "id": r["id"], "column": c, "offset": m.start(), "kind": "secret_pattern"})
                wm += len(WEBMAIL.findall(v))
json.dump({"secret_hits": sh, "unredacted_webmail_in_parquet": wm}, open(P / "manifests/batch1_secret_scan.json", "w"), indent=1)
if sh: fails.append(f"secret_hits={len(sh)}")
if wm: fails.append(f"unredacted_webmail={wm}")
notes["secret_hits"] = len(sh); notes["unredacted_webmail"] = wm
json.dump({"ok": not fails, "fails": fails, "notes": notes}, open(P / "manifests/batch1_verify.json", "w"), indent=1)
files = [{"path": str(f.relative_to(P)), "sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "bytes": f.stat().st_size}
         for f in sorted(P.rglob("*")) if f.is_file() and f.name != "batch1_files.json"]
json.dump(files, open(P / "manifests/batch1_files.json", "w"), indent=1)
print(json.dumps({"ok": not fails, "fails": fails, "notes": notes}))
sys.exit(0 if not fails else 1)
