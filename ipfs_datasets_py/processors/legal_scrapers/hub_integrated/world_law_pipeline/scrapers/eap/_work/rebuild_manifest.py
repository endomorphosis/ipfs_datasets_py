"""Rebuild _scanned_pdfs_manifest.jsonl from published Hub rows of eap places (+ local _pdf/ and staging), excluding PDFs already in state/pdf_ledger.jsonl."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, glob, sys, hashlib
import pyarrow.parquet as pq
from huggingface_hub import HfApi, hf_hub_download
OUT = (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/out/eap"); H = f"{OUT}/_work/hub"
api = HfApi()
places = {"endomorphosis/world_municipal_law": [], "endomorphosis/world_national_law": []}
for repo in places:
    for f in api.list_repo_files(repo, repo_type="dataset"):
        if f.endswith("_html.parquet") and any(f"/data/{c}/" in f for c in ["BN", "MY", "KH", "LA", "MM"]):
            if repo.endswith("national_law") and f.split("/")[-1].startswith(("iso_BN_", "iso_KH_", "iso_MY_", "iso_LA_", "iso_MM_")): continue
            places[repo].append(f)
led_doc, led_sha, led_url = set(), set(), set()
for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/state/pdf_ledger.jsonl")):
    try: r = json.loads(l)
    except Exception: continue
    if r.get("verified") is False: continue
    led_doc.add((r.get("country_code"), r.get("place_key"), r.get("doc_id"))); led_sha.add(r.get("sha256"))
    if r.get("source_url"): led_url.add(r["source_url"])
rows, excl, seen = [], 0, set()
def add(x):
    global excl
    k = (x["country_code"], x["place_key"], x["doc_id"])
    if k in seen: return
    seen.add(k)
    if k in led_doc or (x.get("sha256") and x["sha256"] in led_sha) or x["source_url"] in led_url: excl += 1; return
    rows.append(x)
for repo, fs in places.items():
    for f in fs:
        p = hf_hub_download(repo, f, repo_type="dataset", local_dir=H)
        t = pq.read_table(p)
        cols = t.column_names
        for r in t.to_pylist():
            em = r.get("extra_metadata") or {}
            if isinstance(em, str):
                try: em = json.loads(em)
                except Exception: em = {}
            ts = em.get("text_source") or r.get("text_source")
            cc_ = r.get("content_complete", em.get("content_complete"))
            if not (cc_ is False or ts in ("ocr", "none") or em.get("ocr")): continue
            src = r.get("source_url") or ""
            if not (src.lower().split("?")[0].endswith(".pdf") or r.get("content_format") == "pdf_text"): continue
            pk = f.split("/")[-1].replace("_html.parquet", "")
            lp = em.get("scanned_pdf_local")
            x = {"doc_id": r["doc_id"], "place_key": pk, "country_code": f.split("/")[-2], "source_url": src,
                 "local_path": lp if lp and os.path.exists(lp) else None, "ocr_done": ts == "ocr" or bool(em.get("ocr")),
                 "source_policy": r.get("source_policy") or em.get("source_policy"), "law_file": f"hf://{repo}/{f}"}
            if x["local_path"]:
                b = open(lp, "rb").read(); x.update(sha256=hashlib.sha256(b).hexdigest(), bytes=len(b))
            add(x)
# local _pdf/ files and staging rows (archive runs)
for e in (json.loads(l) for l in open(f"{OUT}/_scanned_pdfs_manifest.new.jsonl")) if os.path.exists(f"{OUT}/_scanned_pdfs_manifest.new.jsonl") else []:
    add(e)
p = f"{OUT}/_scanned_pdfs_manifest.jsonl"
with open(p + ".tmp", "w") as f:
    for x in rows: f.write(json.dumps(x, ensure_ascii=False) + "\n")
    f.flush(); os.fsync(f.fileno())
os.rename(p + ".tmp", p)
from collections import Counter
print("rows", len(rows), "excluded_on_hub", excl, Counter((x["country_code"], x["ocr_done"]) for x in rows))
