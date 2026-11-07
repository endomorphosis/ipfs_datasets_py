from pathlib import Path
from huggingface_hub import HfApi
import pandas as pd

token = open("/home/USER/.cache/huggingface/token").read().strip()
api = HfApi(token=token)

tn_l = len(pd.read_parquet("staging_tn/data/laws.parquet"))
tn_a = len(pd.read_parquet("staging_tn/data/articles.parquet"))
print("TN", tn_l, tn_a)
text = Path("staging_tn/README.md").read_text()
assert text.startswith("---") and f"| {tn_l} |" in text and f"| {tn_a} |" in text
api.upload_folder(folder_path="staging_tn", repo_id="endomorphosis/ipfs_tunisia_laws", repo_type="dataset",
    commit_message=f"Deepen Tunisia laws: {tn_l} laws / {tn_a} articles")
print("uploaded TN")

zw_l = len(pd.read_parquet("staging_zw/data/laws.parquet"))
zw_a = len(pd.read_parquet("staging_zw/data/articles.parquet"))
print("ZW staging", zw_l, zw_a)
if zw_l > 330 or zw_a > 11997:
    text = Path("staging_zw/README.md").read_text()
    assert text.startswith("---") and f"| {zw_l} |" in text and f"| {zw_a} |" in text
    api.upload_folder(folder_path="staging_zw", repo_id="endomorphosis/ipfs_zimbabwe_laws", repo_type="dataset",
        commit_message=f"Deepen Zimbabwe laws: {zw_l} laws / {zw_a} articles")
    print("uploaded ZW", zw_l, zw_a)
else:
    print("ZW skip — already live at 330/11997")
