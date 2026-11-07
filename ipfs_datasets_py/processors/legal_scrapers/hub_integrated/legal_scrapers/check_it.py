import pandas as pd
from pathlib import Path
laws = pd.read_parquet("staging_it/data/laws.parquet")
arts = pd.read_parquet("staging_it/data/articles.parquet")
print("counts", len(laws), len(arts))
text = laws["text"].fillna("").astype(str).str.len()
print("text>=80", int((text>=80).sum()), "text>=500", int((text>=500).sum()), "p50", int(text.quantile(0.5)), "emptyish", int((text<20).sum()))
at = arts["text"].fillna("").astype(str).str.len()
print("art p50", int(at.quantile(0.5)), "art>=80", int((at>=80).sum()))
readme = Path("staging_it/README.md").read_text()
print("yaml", readme.startswith("---"))
print("snapshot_ok", f"| {len(laws)} |" in readme and f"| {len(arts)} |" in readme)
print(readme[readme.find("## Snapshot"):readme.find("## Snapshot")+400])
