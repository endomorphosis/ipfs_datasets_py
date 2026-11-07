# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_WORLD = _ipfs_Path(_ipfs_os.environ.get("WORLD_LAW_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "world_law")))
_TESSDATA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_TESSDATA", str(_ipfs_Path.home() / ".ipfs_datasets" / "tessdata")))
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from huggingface_hub import HfApi
api = HfApi(token=open("/home/USER/.cache/huggingface/token").read().strip())
repo = "endomorphosis/ipfs_senegal_laws"
folder = str(_SCRAPERS) + "/staging_sn"
api.create_repo(repo_id=repo, repo_type="dataset", exist_ok=True)
api.upload_folder(folder_path=folder, repo_id=repo, repo_type="dataset", commit_message="Deepen Senegal JO via archives.sn: 191 laws / 3923 articles (was thin pilot 43/1202)")
print("uploaded", repo)
