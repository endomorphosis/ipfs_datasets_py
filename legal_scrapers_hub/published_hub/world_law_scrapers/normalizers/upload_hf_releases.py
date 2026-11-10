#!/usr/bin/env python3
"""Upload packaged legal-corpora-releases to endomorphosis/ipfs_<slug>_laws."""
from __future__ import annotations
import json, sys
from pathlib import Path
from huggingface_hub import HfApi, create_repo

SECRET = Path(__import__("os").environ.get("HF_TOKEN_FILE", ""))
RELEASES = Path("/workspace/legal-corpora-releases")

def token() -> str:
    d = json.loads(SECRET.read_text())
    t = d.get("token") or d.get("access_token")
    if not t:
        raise SystemExit("no token in secret file")
    return t

def upload_slug(slug: str) -> dict:
    api = HfApi(token=token())
    repo_id = f"endomorphosis/ipfs_{slug}_laws"
    local = RELEASES / slug
    if not local.is_dir():
        raise SystemExit(f"missing {local}")
    create_repo(repo_id, repo_type="dataset", exist_ok=True, token=token(), private=False)
    # upload folder contents
    api.upload_folder(
        folder_path=str(local),
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=f"Refresh {slug} laws research snapshot (incomplete/catalog-backed; official source prevails; not legal advice)",
        ignore_patterns=[".git/**"],
    )
    # mark uploaded in MANIFEST if present
    man = local / "MANIFEST.md"
    if man.exists():
        text = man.read_text(encoding="utf-8")
        text = text.replace("uploaded: false", "uploaded: true")
        man.write_text(text, encoding="utf-8")
    info = api.repo_info(repo_id, repo_type="dataset")
    files = list(api.list_repo_files(repo_id, repo_type="dataset"))
    return {"repo_id": repo_id, "nfiles": len(files), "sha": (info.sha or "")[:12], "files": files[:12]}

def main():
    slugs = sys.argv[1:] or ["bulgaria", "cyprus", "italy", "romania", "slovenia"]
    for slug in slugs:
        print(f"UPLOAD_START {slug}", flush=True)
        try:
            out = upload_slug(slug)
            print(f"UPLOAD_OK {json.dumps(out)}", flush=True)
        except Exception as e:
            print(f"UPLOAD_FAIL {slug} {type(e).__name__}: {e}", flush=True)
            raise

if __name__ == "__main__":
    main()
