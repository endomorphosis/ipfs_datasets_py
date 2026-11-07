from pathlib import Path
from huggingface_hub import HfApi
import pandas as pd

token = open("/home/USER/.cache/huggingface/token").read().strip()
api = HfApi(token=token)

def write_readme(path, slug, title, laws, arts, source, collector, gaps):
    Path(path).write_text(f"""---
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

# DO
do_laws = len(pd.read_parquet("staging_do/data/laws.parquet"))
do_arts = len(pd.read_parquet("staging_do/data/articles.parquet"))
print("DO", do_laws, do_arts)
write_readme(
    "staging_do/README.md", "dominicanrepublic", "Laws of the Dominican Republic",
    do_laws, do_arts,
    "Consultoría Jurídica (consultoria.gov.do) + Biblioteca del Congreso gacetas.",
    "scrapers/collect_do.py",
    "- Catalog incomplete vs Consultoría thousands.\n- SPA decrees thin; yearly gaceta tomos inflate article counts.",
)
api.upload_folder(folder_path="staging_do", repo_id="endomorphosis/ipfs_dominicanrepublic_laws", repo_type="dataset",
    commit_message=f"Deepen Dominican Republic laws: {do_laws} laws / {do_arts} articles")
print("uploaded DO")

# SV
sv_laws = len(pd.read_parquet("staging_sv/data/laws.parquet"))
sv_arts = len(pd.read_parquet("staging_sv/data/articles.parquet"))
print("SV", sv_laws, sv_arts)
write_readme(
    "staging_sv/README.md", "elsalvador", "Laws of El Salvador",
    sv_laws, sv_arts,
    "Asamblea Legislativa / Diario Oficial de El Salvador (asamblea.gob.sv).",
    "scrapers/collect_sv.py",
    "- Catalog incomplete vs Diario/Asamblea corpus.\n- Garbage Diario scans quarantined where applicable.",
)
api.upload_folder(folder_path="staging_sv", repo_id="endomorphosis/ipfs_elsalvador_laws", repo_type="dataset",
    commit_message=f"Deepen El Salvador laws: {sv_laws} laws / {sv_arts} articles")
print("uploaded SV")
