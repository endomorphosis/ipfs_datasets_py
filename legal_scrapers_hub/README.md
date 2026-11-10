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
