# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os, sys, traceback
from huggingface_hub import HfApi, CommitOperationAdd
from pathlib import Path
S = _CORPORA / "hf-staging" / "ipfs_switzerland_laws_cantonal_20260927T082541"
REPO = "endomorphosis/ipfs_switzerland_laws"; TIP = "25cd3f9f14d6e6ee5453bb5ab36a9c2d6e8f8c1c"
api = HfApi(token=os.environ["HF_TOKEN"])
ops = [CommitOperationAdd(path_in_repo=str(p.relative_to(S)), path_or_fileobj=str(p)) for p in sorted(S.rglob("*")) if p.is_file()]
print("ops", [o.path_in_repo for o in ops], flush=True)
try:
    ci = api.create_commit(repo_id=REPO, repo_type="dataset", operations=ops, parent_commit=TIP,
        commit_message="CH cantonal append: +14,994 cantonal laws / +342,194 articles (24 cantons, jurisdiction CH-<canton>); federal rows unchanged",
        commit_description="Append-only. Federal 5,086 laws / 141,697 articles first and field-identical. SZ BLOCKED_SOURCE (3x403), NE robots-disallowed. Never-thin pre-check PASS.")
    print("COMMIT_OK", ci.oid, ci.commit_url, flush=True)
except Exception as e:
    traceback.print_exc(); print("COMMIT_FAIL", repr(e), flush=True); sys.exit(1)
