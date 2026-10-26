#!/usr/bin/env python3
"""EE municipal IR stage 1: pinned source download (rev 9ef422a2a38a) into build/ + normalize -> corpus parquet."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import hashlib, json, os, shutil, sys
from pathlib import Path
os.environ.setdefault("HF_HOME", "/workspace/country-laws-ir/cache/hf")
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
sys.path.insert(0, "/workspace/country-laws-ir")
from huggingface_hub import HfApi, hf_hub_download
from country_laws_ir.catalog import get_country
from country_laws_ir.normalize import load_local_source, build_corpus

SLUG = "estonia_municipal"
C = get_country(SLUG)
TIP = C["revision"]; TS = TIP[:12]; REPO = C["repo"]
BUILD = Path(f"/workspace/country-laws-ir/build/{SLUG}_{TS}")
SRC = BUILD / "src"; CACHE = BUILD / "cache"

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def main():
    api = HfApi(token=False)
    info = api.dataset_info(REPO, revision=TIP, files_metadata=True)
    assert info.sha == TIP, (info.sha, TIP)
    lfs = {s.rfilename: (s.lfs.sha256 if s.lfs else None) for s in info.siblings}
    (SRC / "data").mkdir(parents=True, exist_ok=True); CACHE.mkdir(parents=True, exist_ok=True)
    for fn in ("data/laws.parquet", "data/articles.parquet", "manifest.json", "README.md"):
        p = hf_hub_download(REPO, fn, repo_type="dataset", revision=TIP, token=False)
        dst = SRC / fn; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(p, dst)
        if lfs.get(fn): assert sha(dst) == lfs[fn], f"sha mismatch {fn}"
    (SRC / "pack_meta.json").write_text(json.dumps({"slug": SLUG, "repo": REPO, "source_dataset": REPO,
        "source_revision": TIP, "name": C["name"], "indexable": True}, indent=2) + "\n")
    laws, arts, meta = load_local_source(SRC)
    corpus, rep = build_corpus(laws, arts, meta)
    corpus.to_parquet(CACHE / f"{SLUG}_corpus_{TS}.parquet", index=False)
    out = {"tip": TIP, "n_laws": len(laws), "n_articles": len(arts), "corpus_n": len(corpus), "unit": rep.get("unit"),
           "drops": rep.get("drops"), "n_dropped_total": rep.get("n_dropped_total"),
           "record_types": corpus["record_type"].value_counts().to_dict(),
           "doc_index_ok": bool((corpus["document_index"].tolist() == list(range(len(corpus))))),
           "laws_cols": list(laws.columns), "articles_cols": list(arts.columns),
           "schema_surprises": meta.get("schema_surprises")}
    (BUILD / "prep_result.json").write_text(json.dumps(out, indent=2, default=str, ensure_ascii=False) + "\n")
    print(json.dumps(out, indent=2, default=str, ensure_ascii=False))

if __name__ == "__main__":
    main()
