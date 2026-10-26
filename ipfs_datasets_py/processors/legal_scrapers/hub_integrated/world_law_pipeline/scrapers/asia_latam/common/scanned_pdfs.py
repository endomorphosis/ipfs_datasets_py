"""asia_latam scanned-PDF queue for World Law OCR (raw PDF upload to endomorphosis/world_law_scanned_pdfs via ocr/pdf_collect.py).

File: /workspace/world_law/staging/asia_latam/_scanned_pdfs_manifest.jsonl  (append-only, one JSON object per line,
same record format as out/eap/_scanned_pdfs_manifest.jsonl, i.e. pdf_collect.load_eap):
  doc_id         raw doc_id as in the law row (e.g. "sapl-38"; NOT unique across places -> key is (place_key, doc_id))
  place_key      schema.place_key(place_id), e.g. "wd_Q630661"
  country_code   "BR"
  source_url     the PDF URL to fetch (SAPL texto_integral), not the /norma/<id> HTML page
  local_path     null (always fetched live)
  ocr_done       false
  source_policy  as in the law row ("robots_allowed_rfc9309")
  law_file       hf://endomorphosis/world_municipal_law/world_law/data/BR/<place_key>_html.parquet
Appends are serialized with flock on _scanned_pdfs_manifest.lock and deduplicated by (place_key, doc_id).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import fcntl, json, os
from pathlib import Path

MANIFEST = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam/_scanned_pdfs_manifest.jsonl"))
LOCK = MANIFEST.with_suffix(".lock")
FIELDS = ("doc_id", "place_key", "country_code", "source_url", "local_path", "ocr_done", "source_policy", "law_file")


def record(doc_id, place_key, cc, pdf_url, source_policy, repo="endomorphosis/world_municipal_law"):
    return {"doc_id": doc_id, "place_key": place_key, "country_code": cc, "source_url": pdf_url, "local_path": None,
            "ocr_done": False, "source_policy": source_policy,
            "law_file": f"hf://{repo}/world_law/data/{cc}/{place_key}_html.parquet"}


def append(records):
    """Append records not already present (by (place_key, doc_id)). Returns number written."""
    records = [r for r in records if r.get("doc_id") and r.get("place_key") and r.get("source_url")]
    if not records:
        return 0
    with open(LOCK, "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        have = set()
        if MANIFEST.exists():
            with open(MANIFEST, encoding="utf-8") as f:
                for ln in f:
                    try:
                        d = json.loads(ln); have.add((d["place_key"], d["doc_id"]))
                    except (ValueError, KeyError):
                        pass
        new = []
        for r in records:
            k = (r["place_key"], r["doc_id"])
            if k in have:
                continue
            have.add(k); new.append({f: r.get(f) for f in FIELDS})
        if new:
            with open(MANIFEST, "a", encoding="utf-8") as f:
                f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in new))
                f.flush(); os.fsync(f.fileno())
        return len(new)
