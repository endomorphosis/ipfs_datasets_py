from pathlib import Path
from huggingface_hub import HfApi
import pandas as pd
import re

token = open("/home/USER/.cache/huggingface/token").read().strip()
api = HfApi(token=token)

def ensure_readme(folder, slug, title, source, collector, gaps):
    laws = len(pd.read_parquet(f"{folder}/data/laws.parquet"))
    arts = len(pd.read_parquet(f"{folder}/data/articles.parquet"))
    readme_path = Path(f"{folder}/README.md")
    text = readme_path.read_text() if readme_path.exists() else ""
    ok = (
        text.startswith("---")
        and "Laws / instruments" in text
        and f"| {laws} |" in text
        and f"| {arts} |" in text
    )
    if not ok:
        # may be chmod a-w; try rewrite
        try:
            readme_path.chmod(0o644)
        except Exception:
            pass
        readme_path.write_text(f"""---
license: other
task_categories:
- text-retrieval
language:
- en
tags:
- law
- {slug}
- legislation
pretty_name: {title}
---

# {title} (`ipfs_{slug}_laws`)

{source}

## Snapshot

| Field | Value |
| --- | --- |
| Laws / instruments | {laws} |
| Articles | {arts} |
| Coverage | catalog-backed incomplete |
| Source | {source}
| Collector | {collector} |

## Known gaps

{gaps}

## License

Official legislative texts; reuse subject to source terms. Not legal advice.
""")
        print(folder, "README rewritten")
    else:
        print(folder, "README OK")
    return laws, arts

zw_l, zw_a = ensure_readme(
    "staging_zw", "zimbabwe", "Laws of Zimbabwe",
    "Parliament of Zimbabwe (parlzim.gov.zw Act PDFs; Wayback of official URLs). Veritas/ZimLII excluded.",
    "scrapers/collect_zw.py",
    "- Incomplete vs ~400+ Acts; SI corpus not included.\n- Deepen ongoing.",
)
api.upload_folder(folder_path="staging_zw", repo_id="endomorphosis/ipfs_zimbabwe_laws", repo_type="dataset",
    commit_message=f"Deepen Zimbabwe laws: {zw_l} laws / {zw_a} articles")
print("uploaded ZW", zw_l, zw_a)

tn_l, tn_a = ensure_readme(
    "staging_tn", "tunisia", "Laws of Tunisia",
    "Official JORT via lake.jort.tn / ocr.jort.tn; secondary Wayback legislation.tn PDFs.",
    "scrapers/collect_tn.py",
    "- Incomplete vs JORT ~9.9k Lois + decrees.\n- Deepen ongoing.",
)
api.upload_folder(folder_path="staging_tn", repo_id="endomorphosis/ipfs_tunisia_laws", repo_type="dataset",
    commit_message=f"Deepen Tunisia laws: {tn_l} laws / {tn_a} articles")
print("uploaded TN", tn_l, tn_a)
