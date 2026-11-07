from pathlib import Path
from huggingface_hub import HfApi
import pandas as pd

folder = Path("/tmp/it_upload")
laws = len(pd.read_parquet(folder / "data/laws.parquet"))
arts = len(pd.read_parquet(folder / "data/articles.parquet"))
print("counts", laws, arts)
(folder / "README.md").write_text(f"""---
license: other
task_categories:
- text-retrieval
language:
- it
tags:
- law
- italy
- legislation
- normattiva
pretty_name: Laws of Italy
---

# Laws of Italy (`ipfs_italy_laws`)

Normattiva OpenData BFF (`dettaglio-atto` + `idArticolo` walk). Catalog shells dropped; honest article bodies only.

## Snapshot

| Field | Value |
| --- | --- |
| Laws / instruments | {laws} |
| Articles | {arts} |
| Coverage | catalog-backed incomplete (deepened bodies/articles) |
| Source | Normattiva OpenData BFF (`dettaglio-atto` + `idArticolo` walk) |
| Collector | scrapers/collect_it.py + scrapers/deepen_it_idarticolo.py |
| Snapshot date | 2026-09-04 |

## Known gaps

- Still far below Normattiva ~205k atti (~{100*laws/205000:.1f}% of that baseline).
- Articleization incomplete vs full corpus; further MAX_NEW body-fill needed.
- Not legal advice.

## License

Official legislative texts; reuse subject to Normattiva / Italian open-data terms.
""")
api = HfApi(token=open("/home/USER/.cache/huggingface/token").read().strip())
api.upload_folder(
    folder_path=str(folder),
    repo_id="endomorphosis/ipfs_italy_laws",
    repo_type="dataset",
    commit_message=f"Deepen Italy Normattiva: {laws} laws / {arts} articles (bodies+idArticolo)",
)
print("uploaded", laws, arts)
