from pathlib import Path
from huggingface_hub import HfApi
import pandas as pd
laws = len(pd.read_parquet("staging_ao/data/laws.parquet"))
arts = len(pd.read_parquet("staging_ao/data/articles.parquet"))
print("counts", laws, arts)
text = Path("staging_ao/README.md").read_text()
assert text.startswith("---") and f"| {laws} |" in text and f"| {arts} |" in text
api = HfApi(token=open("/home/USER/.cache/huggingface/token").read().strip())
api.upload_folder(folder_path="staging_ao", repo_id="endomorphosis/ipfs_angola_laws", repo_type="dataset",
    commit_message=f"Deepen Angola laws: {laws} laws / {arts} articles (OCR)")
print("uploaded", laws, arts)
