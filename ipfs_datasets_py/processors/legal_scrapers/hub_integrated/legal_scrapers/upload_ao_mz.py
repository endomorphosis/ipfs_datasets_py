from pathlib import Path
from huggingface_hub import HfApi
import pandas as pd

token = open("/home/USER/.cache/huggingface/token").read().strip()
api = HfApi(token=token)

for folder, slug, kind in [
    ("staging_ao", "angola", "Deepen"),
    ("staging_mz", "mozambique", "Deepen"),
]:
    laws = len(pd.read_parquet(f"{folder}/data/laws.parquet"))
    arts = len(pd.read_parquet(f"{folder}/data/articles.parquet"))
    text = Path(f"{folder}/README.md").read_text()
    assert text.startswith("---") and f"| {laws} |" in text and f"| {arts} |" in text
    api.upload_folder(
        folder_path=folder,
        repo_id=f"endomorphosis/ipfs_{slug}_laws",
        repo_type="dataset",
        commit_message=f"{kind} {slug} laws: {laws} laws / {arts} articles",
    )
    print("uploaded", slug, laws, arts)
