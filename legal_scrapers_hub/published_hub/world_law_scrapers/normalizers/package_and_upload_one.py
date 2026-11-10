#!/workspace/venv/bin/python3
import sys
from pathlib import Path
sys.path.insert(0, "/workspace")
from package_hf_release import package
from huggingface_hub import HfApi, create_repo
import json

cc, slug_notes = sys.argv[1], sys.argv[2:]
coverage = slug_notes[0] if slug_notes else None
notes = slug_notes[1] if len(slug_notes) > 1 else None
info = package(cc, coverage=coverage, notes=notes)
print("PACKAGED", info["repo_id"], "laws", info["laws_rows"], flush=True)
token = json.loads(Path(__import__("os").environ.get("HF_TOKEN_FILE", "")).read_text())["token"]
api = HfApi(token=token)
create_repo(info["repo_id"], repo_type="dataset", exist_ok=True, token=token, private=False)
api.upload_folder(
    folder_path=info["path"], repo_id=info["repo_id"], repo_type="dataset", token=token,
    commit_message=f"Refresh {info['slug']} laws research snapshot (incomplete/catalog-backed; official source prevails; not legal advice)",
    ignore_patterns=[".git/**"],
)
man = Path(info["path"]) / "MANIFEST.md"
if man.exists():
    man.write_text(man.read_text(encoding="utf-8").replace("uploaded: false", "uploaded: true"), encoding="utf-8")
sha = (api.repo_info(info["repo_id"], repo_type="dataset").sha or "")[:12]
print("UPLOADED", info["repo_id"], sha, flush=True)
