from pathlib import Path
from huggingface_hub import HfApi
import pandas as pd
laws = len(pd.read_parquet("staging_zw/data/laws.parquet"))
arts = len(pd.read_parquet("staging_zw/data/articles.parquet"))
print("counts", laws, arts)
text = Path("staging_zw/README.md").read_text()
assert text.startswith("---") and f"| {laws} |" in text and f"| {arts} |" in text
api = HfApi(token=open("/home/USER/.cache/huggingface/token").read().strip())
api.upload_folder(folder_path="staging_zw", repo_id="endomorphosis/ipfs_zimbabwe_laws", repo_type="dataset",
    commit_message=f"Deepen Zimbabwe laws: {laws} laws / {arts} articles")
print("uploaded", laws, arts)
