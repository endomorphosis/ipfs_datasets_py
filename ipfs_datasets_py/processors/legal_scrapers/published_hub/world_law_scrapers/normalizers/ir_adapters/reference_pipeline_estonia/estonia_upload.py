#!/usr/bin/env python3
"""Upload Estonia IR via HfApi.upload_large_folder; token from secrets, never echoed."""
from __future__ import annotations
import json, sys
from pathlib import Path
from huggingface_hub import HfApi, create_repo, repo_exists, whoami, hf_hub_download

SECRET_CANDIDATES = [
    Path(__import__("os").environ.get("HF_TOKEN_FILE", "")),
    Path(__import__("os").environ.get("HF_TOKEN_FILE", "")),
    Path(__import__("os").environ.get("HF_TOKEN_FILE", "")),
    Path(__import__("os").environ.get("HF_TOKEN_FILE", "")),
]
LOCAL = Path("/workspace/country-laws-ir/releases/ipfs_estonia_laws_ir")
REPO = "justicedao/ipfs_estonia_laws_ir"
TIP_SHORT = "902b122cd27e"


def load_token() -> str:
    for p in SECRET_CANDIDATES:
        if not p.is_file():
            continue
        if p.suffix == ".env":
            for line in p.read_text().splitlines():
                if line.startswith("HF_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        else:
            data = json.loads(p.read_text())
            tok = data.get("token") or data.get("access_token")
            if tok:
                return tok
    raise SystemExit("HF token not found")


def main() -> None:
    token = load_token()
    info = whoami(token=token)
    name = info.get("name")
    orgs = [o.get("name") for o in info.get("orgs", [])]
    print(f"whoami={name}")
    print(f"orgs={orgs}")
    if not LOCAL.is_dir():
        raise SystemExit(f"missing {LOCAL}")
    man = json.loads((LOCAL / "manifest.json").read_text())
    if (man.get("vector") or {}).get("status") == "stub":
        raise SystemExit("refusing upload: vector status is stub")
    if man["counts"]["corpus_rows"] != man["counts"]["vector_rows"]:
        raise SystemExit("refusing upload: corpus_rows != vector_rows")
    tip = str(man.get("dataset_revision") or "")
    if not tip:
        tip = str(((man.get("source") or {}).get("source_revision")) or ((man.get("country") or {}).get("source_revision")) or "")
    if not tip.startswith(TIP_SHORT):
        raise SystemExit(f"refusing upload: tip {tip[:12]} != {TIP_SHORT}")
    if not repo_exists(REPO, repo_type="dataset", token=token):
        url = create_repo(REPO, repo_type="dataset", private=False, exist_ok=True, token=token)
        print(f"created={url}")
    else:
        print("repo_exists=True")
    api = HfApi(token=token)
    print(f"uploading {LOCAL} -> {REPO} via upload_large_folder")
    if hasattr(api, "upload_large_folder"):
        api.upload_large_folder(
            repo_id=REPO,
            folder_path=str(LOCAL),
            repo_type="dataset",
            num_workers=4,
            print_report=True,
            ignore_patterns=["**/__pycache__/**", "**/*.pyc", "**/.cache/**"],
        )
    else:
        api.upload_folder(
            folder_path=str(LOCAL),
            repo_id=REPO,
            repo_type="dataset",
            ignore_patterns=["**/__pycache__/**", "**/*.pyc", "**/.cache/**"],
        )
    info2 = api.dataset_info(REPO)
    print(f"hub_url=https://huggingface.co/datasets/{REPO}")
    print(f"hub_sha={info2.sha}")
    print(f"hub_sha_short={info2.sha[:12] if info2.sha else None}")
    path = hf_hub_download(REPO, "manifest.json", repo_type="dataset", token=token)
    man2 = json.loads(Path(path).read_text())
    print(f"hub_tip={man2.get('dataset_revision')}")
    print(f"hub_corpus_rows={man2['counts'].get('corpus_rows')}")
    print(f"hub_vector_rows={man2['counts'].get('vector_rows')}")
    print(f"hub_vector_status={(man2.get('vector') or {}).get('status')}")
    # write short upload result for report writer
    out = {
        "hub_url": f"https://huggingface.co/datasets/{REPO}",
        "ir_commit": info2.sha,
        "ir_commit_short": info2.sha[:12] if info2.sha else None,
        "hub_tip": man2.get("dataset_revision"),
        "hub_corpus_rows": man2["counts"].get("corpus_rows"),
        "hub_vector_rows": man2["counts"].get("vector_rows"),
        "hub_vector_status": (man2.get("vector") or {}).get("status"),
    }
    Path("/workspace/country-laws-ir/reports/estonia_upload_902b122cd27e.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
