#!/usr/bin/env python3
"""Upload staging packages to Hugging Face datasets. Never prints token."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import re
import sys
import time
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(str(_SCRAPERS))
TOKEN_PATH = Path("/home/USER/.cache/huggingface/token")
RESULTS = ROOT / "upload_backlog_results.json"

PACKAGES = [
    # creates
    ("staging_zw", "endomorphosis/ipfs_zimbabwe_laws", "Zimbabwe", 80, 3775),
    ("staging_tz", "endomorphosis/ipfs_tanzania_laws", "Tanzania", 60, 1329),
    ("staging_rs", "endomorphosis/ipfs_serbia_laws", "Serbia", 66, 1037),
    ("staging_al", "endomorphosis/ipfs_albania_laws", "Albania", 60, 3120),
    ("staging_ba", "endomorphosis/ipfs_bosnia_laws", "Bosnia", 50, 2764),
    ("staging_bw", "endomorphosis/ipfs_botswana_laws", "Botswana", 80, 477),
    ("staging_mz", "endomorphosis/ipfs_mozambique_laws", "Mozambique", 91, 2937),
    # deepens
    ("staging_tn", "endomorphosis/ipfs_tunisia_laws", "Tunisia", 248, 12908),
    ("staging_et", "endomorphosis/ipfs_ethiopia_laws", "Ethiopia", 64, 80),
    ("staging_do", "endomorphosis/ipfs_dominicanrepublic_laws", "Dominican Republic", 90, 92457),
    ("staging_sv", "endomorphosis/ipfs_elsalvador_laws", "El Salvador", 106, 5770),
    ("staging_cm", "endomorphosis/ipfs_cameroon_laws", "Cameroon", 300, 1062),
]


def load_token() -> str:
    tok = TOKEN_PATH.read_text().strip()
    if not tok:
        raise SystemExit("HF token empty")
    return tok


def verify_parquet(staging: Path, exp_l: int, exp_a: int) -> tuple[int, int]:
    import pyarrow.parquet as pq
    laws = pq.read_table(staging / "data" / "laws.parquet").num_rows
    arts = pq.read_table(staging / "data" / "articles.parquet").num_rows
    if laws != exp_l or arts != exp_a:
        raise ValueError(f"parquet mismatch {staging}: {laws}/{arts} vs {exp_l}/{exp_a}")
    return laws, arts


def upload_one(api: HfApi, staging: str, repo: str, country: str, exp_l: int, exp_a: int) -> dict:
    folder = ROOT / staging
    result = {
        "staging": staging,
        "repo": repo,
        "country": country,
        "expected_laws": exp_l,
        "expected_articles": exp_a,
        "status": "pending",
        "laws": None,
        "articles": None,
        "url": f"https://huggingface.co/datasets/{repo}",
        "errors": [],
        "commit": None,
    }
    try:
        laws, arts = verify_parquet(folder, exp_l, exp_a)
        result["laws"] = laws
        result["articles"] = arts
    except Exception as e:
        result["status"] = "verify_failed"
        result["errors"].append(str(e))
        return result

    try:
        api.create_repo(repo_id=repo, repo_type="dataset", exist_ok=True)
    except Exception as e:
        result["status"] = "create_repo_failed"
        result["errors"].append(f"create_repo: {e}")
        return result

    commit_msg = f"Create/Update {country} laws: {laws} laws / {arts} articles"
    try:
        info = api.upload_folder(
            folder_path=str(folder),
            repo_id=repo,
            repo_type="dataset",
            commit_message=commit_msg,
            ignore_patterns=["MANIFEST.md", ".cache/**", "**/__pycache__/**"],
        )
        result["commit"] = getattr(info, "commit_url", None) or getattr(info, "oid", None) or str(info)
        result["status"] = "uploaded"
    except Exception as e:
        result["status"] = "upload_failed"
        result["errors"].append(f"upload_folder: {e}")
    return result


def main() -> int:
    only = sys.argv[1:]  # optional staging names filter
    token = load_token()
    api = HfApi(token=token)

    # load prior results if any
    prior = {}
    if RESULTS.exists():
        try:
            for r in json.loads(RESULTS.read_text()):
                prior[r["staging"]] = r
        except Exception:
            pass

    results = []
    packages = PACKAGES
    if only:
        packages = [p for p in PACKAGES if p[0] in only]

    for staging, repo, country, exp_l, exp_a in packages:
        print(f"=== Uploading {staging} -> {repo} ({country} {exp_l}/{exp_a}) ===", flush=True)
        # disk check
        import shutil
        free_g = shutil.disk_usage("/workspace").free / (1024**3)
        if free_g < 20:
            print(f"DISK STOP: free={free_g:.1f}G < 20G", flush=True)
            results.append({
                "staging": staging, "repo": repo, "country": country,
                "status": "disk_stop", "laws": exp_l, "articles": exp_a,
                "url": f"https://huggingface.co/datasets/{repo}",
                "errors": [f"free disk {free_g:.1f}G < 20G"],
            })
            break
        t0 = time.time()
        r = upload_one(api, staging, repo, country, exp_l, exp_a)
        r["elapsed_sec"] = round(time.time() - t0, 1)
        print(f"  -> {r['status']} L/A={r.get('laws')}/{r.get('articles')} err={r.get('errors')}", flush=True)
        results.append(r)
        # write incremental
        merged = {**prior}
        for x in results:
            merged[x["staging"]] = x
        # preserve order of PACKAGES
        out = [merged.get(p[0], {"staging": p[0], "status": "not_run"}) for p in PACKAGES]
        # also include any prior not in list
        RESULTS.write_text(json.dumps(out, indent=2))

    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
