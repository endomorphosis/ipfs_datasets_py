"""Rebuild the eap scanned-PDF manifest: published Hub rows of eap places + staged eap rows with
content_complete=false / text_source in (ocr, none); excludes PDFs already in state/pdf_ledger.jsonl.
Writes out/eap/_scanned_pdfs_manifest.jsonl and a durable copy in staging/eap/_eap_work/. Run with bash -l."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, glob, hashlib
import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download
W = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eap/_eap_work"); H = f"{W}/hub"
OUTS = [(_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/eap/_scanned_pdfs_manifest.jsonl"), f"{W}/_scanned_pdfs_manifest.jsonl"]
led_doc, led_sha, led_url = set(), set(), set()
for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/pdf_ledger.jsonl")):
    try: r = json.loads(l)
    except Exception: continue
    if r.get("verified") is False: continue
    led_doc.add((r.get("place_key"), r.get("doc_id"))); led_sha.add(r.get("sha256"))
    if r.get("source_url"): led_url.add(r["source_url"])
rows, excl, seen = [], 0, set()
def add(x):
    global excl
    k = (x["place_key"], x["doc_id"])
    if k in seen: return
    seen.add(k)
    if k in led_doc or (x.get("sha256") and x["sha256"] in led_sha) or x["source_url"] in led_url: excl += 1; return
    rows.append(x)
def is_scan(r, em):
    ts = em.get("text_source") or r.get("text_source"); cc_ = r.get("content_complete", em.get("content_complete"))
    if not (cc_ is False or ts in ("ocr", "none") or em.get("ocr")): return None
    src = r.get("source_url") or ""
    if not (src.lower().split("?")[0].endswith(".pdf") or r.get("content_format") == "pdf_text"): return None
    return ts == "ocr" or bool(em.get("ocr"))
api = HfApi()
for repo in ["endomorphosis/world_municipal_law", "endomorphosis/world_national_law"]:
    for f in api.list_repo_files(repo, repo_type="dataset"):
        if not f.endswith("_html.parquet") or not any(f"/data/{c}/" in f for c in ["BN", "MY", "KH", "LA", "MM", "TW", "NZ", "KR"]): continue
        name = f.split("/")[-1]
        if repo.endswith("national_law") and name.startswith(("iso_BN_", "iso_KH_", "iso_MY_", "iso_LA_", "iso_MM_", "iso_TW_", "iso_NZ_", "iso_KR_")): continue
        t = pq.read_table(hf_hub_download(repo, f, repo_type="dataset", local_dir=H))
        for r in t.to_pylist():
            em = r.get("extra_metadata") or {}
            if isinstance(em, str):
                try: em = json.loads(em)
                except Exception: em = {}
            if not str(r.get("source_platform", "")) and not em: continue
            o = is_scan(r, em)
            if o is None: continue
            lp = em.get("scanned_pdf_local"); lp = lp if lp and os.path.exists(lp) else None
            x = {"doc_id": r["doc_id"], "place_key": name.replace("_html.parquet", ""), "country_code": f.split("/")[-2], "source_url": r.get("source_url") or "",
                 "local_path": lp, "ocr_done": o, "source_policy": r.get("source_policy") or em.get("source_policy"), "law_file": f"hf://{repo}/{f}"}
            if lp: b = open(lp, "rb").read(); x.update(sha256=hashlib.sha256(b).hexdigest(), bytes=len(b))
            add(x)
for fn in glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/eap/*/*.jsonl")):
    if "/_" in fn: continue
    for l in open(fn):
        r = json.loads(l); o = is_scan(r, r.get("extra_metadata") or {})
        if o is None: continue
        lp = r.get("scanned_pdf_local"); lp = lp if lp and os.path.exists(lp) else None
        x = {"doc_id": r["doc_id"], "place_key": os.path.basename(fn).split(".")[0], "country_code": r["country_code"], "source_url": r["source_url"],
             "local_path": lp, "ocr_done": o, "source_policy": r.get("source_policy"), "law_file": fn}
        if lp: b = open(lp, "rb").read(); x.update(sha256=hashlib.sha256(b).hexdigest(), bytes=len(b))
        add(x)
for p in OUTS:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f:
        for x in rows: f.write(json.dumps(x, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())
    os.rename(p + ".tmp", p)
from collections import Counter
print("rows", len(rows), "excluded_on_hub", excl, dict(Counter(x["country_code"] for x in rows)))
