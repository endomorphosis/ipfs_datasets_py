# Normalizer snapshot

`country_laws_ir/` and `country_laws_ir_scripts/` are a verbatim copy of
`github.com/endomorphosis/ipfs_datasets_py` @ `a1b5c73e5b687d8bd6c3b3051788860fd6e2f07a` (2026-10-07),
path `ipfs_datasets_py/processors/legal_scrapers/` (country_laws_ir v0.5.0, schema `country-laws-ir-graphrag/v1`).
Canonical source of truth stays upstream; this is a convenience snapshot next to the collectors.

Run (CPU; add `--skip-vectors` when torch/sentence-transformers is absent):

    cd normalizers
    python -m country_laws_ir build --source-repo endomorphosis/ipfs_<slug>_laws --skip-vectors --device cpu
    # sharded raw repos (data/laws-00001.parquet ...) first need either the one-file pack:
    python pack_raw_for_ir.py endomorphosis/ipfs_<slug>_laws --out /tmp/pack_<slug>
    python -m country_laws_ir build --source-repo /tmp/pack_<slug> --skip-vectors --device cpu
    # or upstream shard support: patch -p0 country_laws_ir/normalize.py < shard_support.patch

Additions in this directory (not upstream): `schema.py` (pinned raw/IR Arrow schemas + cast/validate), `pack_raw_for_ir.py`,
`shard_support.patch` (makes `load_source` read sharded raw repos; tested on endomorphosis/ipfs_kenya_municipal_laws: 938 laws / 7968 articles).
Docs: ../SCHEMA.md
