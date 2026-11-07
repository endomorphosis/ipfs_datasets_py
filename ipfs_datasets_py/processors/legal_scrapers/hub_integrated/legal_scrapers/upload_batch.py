from pathlib import Path
from huggingface_hub import HfApi
import pandas as pd

token = open("/home/USER/.cache/huggingface/token").read().strip()
api = HfApi(token=token)

jobs = [
    ("staging_na", "namibia", "Create"),
    ("staging_md", "moldova", "Deepen"),
    ("staging_mz", "mozambique", "Deepen"),
    ("staging_ge", "georgia", "Deepen"),
]

for folder, slug, kind in jobs:
    laws = len(pd.read_parquet(f"{folder}/data/laws.parquet"))
    arts = len(pd.read_parquet(f"{folder}/data/articles.parquet"))
    text = Path(f"{folder}/README.md").read_text()
    assert text.startswith("---"), folder
    assert "Laws / instruments" in text, folder
    assert f"| {laws} |" in text and f"| {arts} |" in text, (folder, laws, arts)
    repo = f"endomorphosis/ipfs_{slug}_laws"
    api.create_repo(repo_id=repo, repo_type="dataset", exist_ok=True)
    api.upload_folder(
        folder_path=folder,
        repo_id=repo,
        repo_type="dataset",
        commit_message=f"{kind} {slug} laws: {laws} laws / {arts} articles",
    )
    print("uploaded", slug, laws, arts)

# AO interim if past 121 and README ok
ao = Path("staging_ao")
if (ao / "data/laws.parquet").exists():
    laws = len(pd.read_parquet(ao / "data/laws.parquet"))
    arts = len(pd.read_parquet(ao / "data/articles.parquet"))
    print("AO staging", laws, arts)
    if laws > 121:
        readme = ao / "README.md"
        text = readme.read_text() if readme.exists() else ""
        if text.startswith("---") and f"| {laws} |" in text and f"| {arts} |" in text:
            api.upload_folder(
                folder_path="staging_ao",
                repo_id="endomorphosis/ipfs_angola_laws",
                repo_type="dataset",
                commit_message=f"Deepen Angola laws: {laws} laws / {arts} articles (OCR climb)",
            )
            print("uploaded AO", laws, arts)
        else:
            print("AO skip — README not frozen/matching yet")
