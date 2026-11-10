# legal_scrapers_hub (not part of the installed package)

Mirror copies of Hugging Face dataset scripts and published hub trees that
used to live under `ipfs_datasets_py/processors/legal_scrapers/`. They were
moved here unchanged so they are no longer importable or shipped in wheels
(`setup.py`/`pyproject.toml` only package `ipfs_datasets_py*`).

Nothing in `ipfs_datasets_py` or `tests/` imports or reads these files.
The published copies live on the corresponding Hugging Face datasets.
This directory is a staging area for a separate `legal_scrapers_hub`
repository or HF artifact; that placement still needs owner sign-off.

| Path | From | Moved in |
| --- | --- | --- |
| `hub_dataset_scripts/justicedao__ipfs_*_laws_ir/` (63 kits) | `processors/legal_scrapers/hub_dataset_scripts/` | phase 3a |
| `published_hub/` (1,603 files) | `processors/legal_scrapers/published_hub/` | phase 3b |
| `hub_integrated/justicedao_world_law_scrapers/` (368 files) | `processors/legal_scrapers/hub_integrated/justicedao_world_law_scrapers/` | phase 3c |

Phase 3c kept 7 files in the package at `hub_integrated/justicedao_world_law_scrapers/collectors/` because the `national_collectors` `vendored_path()` shims (collect_additions, collect_es_seue, collect_it_dait, collect_lu_sparql, collect_ua_zip, collect_us_local) point at them: `add_collect.py`, `es_seue_collect.py`, `fr_scdl_collect.py`, `it_dait_collect.py`, `lu_sparql_collect.py`, `ua_zip_collect.py`, `us_local_collect.py`. The moved `MANIFEST.json` still lists them; they were not duplicated here.
